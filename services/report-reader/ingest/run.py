"""Ingestion entry point. Runs as a Kubernetes Job (k8s/40-report-ingest.yaml) or locally.

    python -m ingest.run --manifest s3://spendcheck-reports/manifest.csv
    python -m ingest.run --manifest ./data/reports/manifest.csv          # local files, no AWS

The manifest lists every report once, so metadata never has to be guessed from file names:

    doc_id,corpus,company,ticker,fiscal_year,path
    sgx/D05/2024,sgx,DBS Group Holdings,D05,2024,raw/sgx/D05_2024.pdf
    3M_2018_10K,financebench,3M,MMM,2018,raw/financebench/3M_2018_10K.pdf

`path` is relative to the manifest's folder (or bucket). Documents already in reports.documents
are skipped unless --force is given, so re-running the Job after adding PDFs is cheap.
"""

import argparse
import csv
import io
import logging
import os
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import boto3

from app.config import get_settings
from app.embeddings import Embedder
from app.store import create_pool

from .chunking import chunk_pages
from .pdf_parse import parse_pdf

log = logging.getLogger("ingest")


def _split_s3(uri: str) -> tuple[str, str]:
    bucket, _, key = uri.removeprefix("s3://").partition("/")
    return bucket, key


def read_manifest(manifest: str) -> list[dict]:
    if manifest.startswith("s3://"):
        bucket, key = _split_s3(manifest)
        body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
        return list(csv.DictReader(io.StringIO(body)))
    with open(manifest, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fetch_pdf(manifest: str, relative_path: str, workdir: Path) -> tuple[Path, str]:
    """Return (local file path, source URI) for one report, downloading from S3 if needed."""
    if manifest.startswith("s3://"):
        bucket, key = _split_s3(manifest)
        key = str(Path(key).parent / relative_path).replace("\\", "/").lstrip("./")
        local = workdir / Path(relative_path).name
        boto3.client("s3").download_file(bucket, key, str(local))
        return local, f"s3://{bucket}/{key}"
    local = Path(manifest).parent / relative_path
    return local, str(local)


def store_document(pool, row: dict, source_uri: str, n_pages: int, chunks, vectors, force: bool) -> None:
    """Write one document and all its chunks in a single transaction (all or nothing)."""
    year = int(row["fiscal_year"]) if row.get("fiscal_year") else None
    with pool.connection() as conn, conn.transaction():
        if force:
            conn.execute("DELETE FROM reports.documents WHERE doc_id = %s", (row["doc_id"],))   # chunks cascade
        conn.execute(
            "INSERT INTO reports.documents (doc_id, corpus, company, ticker, fiscal_year, source_uri, n_pages) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (row["doc_id"], row["corpus"], row["company"], row.get("ticker") or None, year, source_uri, n_pages),
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO reports.chunks (doc_id, page, chunk_type, content, embedding) VALUES (%s, %s, %s, %s, %s)",
                [(row["doc_id"], c.page, c.chunk_type, c.content, v) for c, v in zip(chunks, vectors)],
            )


def prepare(local_path: str, company: str, fiscal_year: int | None) -> tuple[int, list]:
    """Parse and chunk one PDF. Runs in a worker process: PDF parsing (mostly table detection,
    about 1 s per page) is the slow, CPU-bound step, so several reports are parsed in parallel."""
    pages = parse_pdf(local_path)
    return len(pages), chunk_pages(pages, company, fiscal_year)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest annual-report PDFs into pgvector")
    parser.add_argument("--manifest", required=True, help="s3://bucket/manifest.csv or a local path")
    parser.add_argument("--only", help="ingest just this doc_id")
    parser.add_argument("--force", action="store_true", help="re-ingest documents that already exist")
    parser.add_argument("--workers", type=int, default=min(6, os.cpu_count() or 1),
                        help="PDFs parsed in parallel (default: up to 6)")
    args = parser.parse_args()

    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")
    started = time.perf_counter()
    settings = get_settings()
    pool = create_pool(settings.database_url)
    embedder = Embedder(settings.embedding_model, settings.embedding_cache_dir)

    with pool.connection() as conn:
        existing = {r[0] for r in conn.execute("SELECT doc_id FROM reports.documents")}

    rows = [r for r in read_manifest(args.manifest) if not args.only or r["doc_id"] == args.only]
    todo = [r for r in rows if args.force or r["doc_id"] not in existing]
    log.info("%d documents in manifest, %d to ingest, %d workers", len(rows), len(todo), args.workers)
    failed = 0

    # Workers parse and chunk; this process embeds and writes, one finished document at a time.
    with tempfile.TemporaryDirectory() as tmp, ProcessPoolExecutor(max_workers=args.workers) as workers:
        jobs = {}
        for row in todo:
            local, source_uri = fetch_pdf(args.manifest, row["path"], Path(tmp))
            year = int(row["fiscal_year"]) if row.get("fiscal_year") else None
            jobs[workers.submit(prepare, str(local), row["company"], year)] = (row, source_uri)
        for job in as_completed(jobs):
            row, source_uri = jobs[job]
            try:
                n_pages, chunks = job.result()
                vectors = embedder.embed_passages(c.content for c in chunks)
                store_document(pool, row, source_uri, n_pages, chunks, vectors, args.force)
                log.info("ingested %s: %d pages, %d chunks", row["doc_id"], n_pages, len(chunks))
            except Exception:   # one bad PDF must not stop the batch
                failed += 1
                log.exception("failed to ingest %s", row["doc_id"])

    pool.close()
    log.info("done: %d ingested, %d failed, %.0f s", len(todo) - failed, failed, time.perf_counter() - started)


if __name__ == "__main__":
    main()
