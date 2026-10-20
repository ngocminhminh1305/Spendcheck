"""Module 5 retrieval: find the report pages most likely to contain the answer.

Two modes, so the evaluation can show that gains come from our design and not just from the LLM
(proposal, Evaluation Plan, Module 5):

  basic  dense top-k over every chunk of every report (the "same LLM with basic retrieval")
  full   1. scope:  restrict to the right report(s), from the request filters or by spotting a
                    company name, alias or ticker and a year in the question
         2. expand: add statement vocabulary for finance concepts in the question (glossary.py)
         3. hybrid: dense search + full-text search inside that scope (candidate_k each)
         4. fuse:   reciprocal rank fusion, score = sum of 1 / (60 + rank)
         5. pages:  the best top_pages pages, each given in full (all its chunks), because
                    citations are per page and a statement table should never be cut in half
"""

import re
from dataclasses import replace

from psycopg_pool import ConnectionPool

from . import store
from .config import Settings
from .embeddings import Embedder
from .glossary import expansion_terms
from .schemas import AskRequest, DocumentInfo
from .store import ChunkHit

# Everyday names that do not appear in the official company name, mapped to SGX codes.
ALIASES = {
    "dbs": "D05", "development bank of singapore": "D05",
    "sia": "C6L", "singapore airlines": "C6L",
    "singtel": "Z74", "singapore telecommunications": "Z74",
    "cict": "C38U", "capitaland integrated commercial trust": "C38U",
    "sheng siong": "OV8",
}
# Words dropped to get a company's short name: "DBS Group Holdings" -> "dbs".
_SUFFIXES = {"group", "holdings", "holding", "limited", "ltd", "inc", "corp", "corporation",
             "company", "co", "plc", "the", "trust", "reit", "bhd"}
_YEAR = re.compile(r"\b(?:fy\s?)?(20\d{2})\b")
_SHORT_FY = re.compile(r"\bfy\s?(\d{2})\b")


def _names(doc: DocumentInfo) -> set[str]:
    """Ways a question might refer to this document's company."""
    full = doc.company.lower()
    short = " ".join(w for w in re.findall(r"[a-z0-9&]+", full) if w not in _SUFFIXES)
    names = {full, short}
    if doc.ticker and len(doc.ticker) >= 3:   # 2-letter tickers ("ON", "IT") are ordinary words
        names.add(doc.ticker.lower())
    names.update(alias for alias, ticker in ALIASES.items() if doc.ticker and ticker == doc.ticker.upper())
    return {n for n in names if len(n) >= 2}


def _mentions(question: str, doc: DocumentInfo) -> bool:
    return any(re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", question) for name in _names(doc))


def year_in(question: str) -> int | None:
    if m := _YEAR.search(question):
        return int(m.group(1))
    if m := _SHORT_FY.search(question):
        return 2000 + int(m.group(1))
    return None


def resolve_scope(request: AskRequest, documents: list[DocumentInfo]) -> list[str] | None:
    """doc_ids to search, or None to search every document.

    Uses explicit filters from the request first, otherwise looks for the company and year in
    the question. A year only narrows the choice when that company has a report for that year.
    """
    if request.doc_id:
        return [request.doc_id]
    question = request.question.lower()
    if request.company:
        wanted = request.company.lower()
        candidates = [d for d in documents if wanted in _names(d) or wanted == d.company.lower()]
    else:
        candidates = [d for d in documents if _mentions(question, d)]
    if not candidates:
        return None
    year = request.fiscal_year or year_in(question)
    same_year = [d for d in candidates if year and d.fiscal_year == year]
    return [d.doc_id for d in (same_year or candidates)]


def reciprocal_rank_fusion(rankings: list[list[ChunkHit]], k: int, c: int = 60) -> list[ChunkHit]:
    """Merge ranked lists: a chunk ranked high by either search, or fairly high by both, wins."""
    scores: dict[int, float] = {}
    hits: dict[int, ChunkHit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (c + rank)
            hits.setdefault(hit.chunk_id, hit)
    best = sorted(scores, key=scores.get, reverse=True)[:k]
    return [replace(hits[i], score=round(scores[i], 5)) for i in best]


_PREFIX_LINE = re.compile(r"^.*, page \d+:\n")


def whole_pages(ranked: list[ChunkHit], page_chunks: list[ChunkHit], max_pages: int,
                max_chars: int = 8000) -> list[ChunkHit]:
    """Turn ranked chunks into ranked pages: the best max_pages distinct pages, each rebuilt from
    all of its chunks (tables first, then text, in document order)."""
    order: list[tuple[str, int]] = []
    best: dict[tuple[str, int], ChunkHit] = {}
    for hit in ranked:
        key = (hit.doc_id, hit.page)
        if key not in best:
            best[key] = hit
            order.append(key)
    by_page: dict[tuple[str, int], list[ChunkHit]] = {}
    for chunk in page_chunks:
        by_page.setdefault((chunk.doc_id, chunk.page), []).append(chunk)

    pages = []
    for key in order[:max_pages]:
        top = best[key]
        parts = [_PREFIX_LINE.sub("", c.content, count=1) for c in by_page.get(key, [top])]
        prefix = _PREFIX_LINE.match(top.content)
        body = "\n\n".join(parts)[:max_chars]
        pages.append(replace(top, chunk_type="page", content=(prefix.group(0) if prefix else "") + body))
    return pages


def retrieve(request: AskRequest, *, pool: ConnectionPool, embedder: Embedder, settings: Settings) -> list[ChunkHit]:
    """Top chunks (basic) or top whole pages (full) for the question."""
    query_vec = embedder.embed_query(request.question)
    if request.mode == "basic":
        return store.search_dense(pool, query_vec, request.top_k or settings.top_k)

    scope = resolve_scope(request, store.list_documents(pool))
    extra = expansion_terms(request.question)
    rankings = [
        store.search_dense(pool, query_vec, settings.candidate_k, scope),
        store.search_fulltext(pool, f"{request.question} {extra}", settings.candidate_k, scope),
    ]
    if extra:   # also look for passages that read like the statement lines themselves
        rankings.append(store.search_dense(pool, embedder.embed_query(extra), settings.candidate_k, scope))
    ranked = reciprocal_rank_fusion(rankings, settings.candidate_k)
    n_pages = request.top_k or settings.top_pages
    top_pages = list(dict.fromkeys((h.doc_id, h.page) for h in ranked))[:n_pages]
    return whole_pages(ranked, store.chunks_on_pages(pool, top_pages), n_pages)
