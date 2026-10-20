"""Access to the reports schema (documents + chunks with pgvector embeddings)."""

import re
from dataclasses import dataclass

import numpy as np
from pgvector.psycopg import register_vector
from psycopg.rows import class_row, dict_row
from psycopg_pool import ConnectionPool

from .schemas import DocumentInfo

_COLUMNS = "c.chunk_id, c.doc_id, d.company, d.fiscal_year, c.page, c.chunk_type, c.content"
_TERM = re.compile(r"[a-z0-9]+")


@dataclass
class ChunkHit:
    """One retrieved chunk, with everything needed to cite it."""

    chunk_id: int
    doc_id: str
    company: str
    fiscal_year: int | None
    page: int
    chunk_type: str
    content: str
    score: float


def create_pool(database_url: str) -> ConnectionPool:
    # register_vector teaches psycopg to send/receive numpy arrays as pgvector values.
    return ConnectionPool(database_url, min_size=1, max_size=5, open=True, configure=register_vector)


def ping(pool: ConnectionPool) -> bool:
    try:
        with pool.connection(timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def list_documents(pool: ConnectionPool) -> list[DocumentInfo]:
    with pool.connection() as conn, conn.cursor(row_factory=class_row(DocumentInfo)) as cur:
        cur.execute(
            "SELECT doc_id, corpus, company, ticker, fiscal_year, n_pages "
            "FROM reports.documents ORDER BY company, fiscal_year DESC"
        )
        return cur.fetchall()


def search_dense(pool: ConnectionPool, query_vec: np.ndarray, k: int,
                 doc_ids: list[str] | None = None) -> list[ChunkHit]:
    """Nearest chunks by cosine similarity (pgvector HNSW index), optionally only inside doc_ids."""
    where = "WHERE c.doc_id = ANY(%(docs)s)" if doc_ids else ""
    sql = (f"SELECT {_COLUMNS}, 1 - (c.embedding <=> %(q)s) AS score "
           f"FROM reports.chunks c JOIN reports.documents d USING (doc_id) {where} "
           f"ORDER BY c.embedding <=> %(q)s LIMIT %(k)s")
    with pool.connection() as conn, conn.transaction():
        # With a filter, an approximate index scan can return fewer than k rows; iterative scan
        # (pgvector 0.8+) keeps scanning until it has k matching rows, in exact order.
        conn.execute("SET LOCAL hnsw.iterative_scan = strict_order")
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, {"q": query_vec, "k": k, "docs": doc_ids})
            return [ChunkHit(**row) for row in cur.fetchall()]


def chunks_on_pages(pool: ConnectionPool, pages: list[tuple[str, int]]) -> list[ChunkHit]:
    """Every chunk on the given (doc_id, page) pairs, in document order."""
    if not pages:
        return []
    sql = (f"SELECT {_COLUMNS}, 0.0 AS score "
           f"FROM reports.chunks c JOIN reports.documents d USING (doc_id) "
           f"JOIN unnest(%(docs)s::text[], %(pages)s::int[]) AS want(doc_id, page) USING (doc_id, page) "
           f"ORDER BY c.chunk_id")
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"docs": [d for d, _ in pages], "pages": [p for _, p in pages]})
        return [ChunkHit(**row) for row in cur.fetchall()]


def search_fulltext(pool: ConnectionPool, query: str, k: int,
                    doc_ids: list[str] | None = None) -> list[ChunkHit]:
    """Keyword search with Postgres full-text search. It catches exact terms that embeddings can
    miss, e.g. "CET1 ratio", "distribution per unit", "net interest margin".

    Terms are OR-ed (any word may match) and ranked by how many match and how close together,
    because AND-ing every word of a full question usually matches nothing.
    """
    terms = [t for t in _TERM.findall(query.lower()) if len(t) > 1][:30]
    if not terms:
        return []
    where = "AND c.doc_id = ANY(%(docs)s)" if doc_ids else ""
    sql = (f"SELECT {_COLUMNS}, ts_rank_cd(c.tsv, q) AS score "
           f"FROM reports.chunks c JOIN reports.documents d USING (doc_id), "
           f"to_tsquery('english', %(tsq)s) q "
           f"WHERE c.tsv @@ q {where} ORDER BY score DESC LIMIT %(k)s")
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"tsq": " | ".join(terms), "k": k, "docs": doc_ids})
        return [ChunkHit(**row) for row in cur.fetchall()]
