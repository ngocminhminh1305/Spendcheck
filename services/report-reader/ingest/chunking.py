"""Step 2 of ingestion: split parsed pages into retrieval-sized chunks.

Rules
  * A chunk never crosses a page boundary, so every chunk has exactly one page to cite.
  * Each table is its own chunk (chunk_type='table'). Long tables are split by rows with the
    header row repeated, so numbers keep their column labels.
  * Text is packed paragraph by paragraph into chunks of up to max_chars, with an overlap so a
    fact that straddles two chunks is still found.
  * Every chunk starts with "{company} FY{year}, page {n}:" which helps retrieval when many
    reports use the same wording, and tells the LLM where the text came from.
"""

import re
from dataclasses import dataclass

from .pdf_parse import ParsedPage

MIN_CONTENT_CHARS = 30   # skip near-empty fragments


@dataclass
class Chunk:
    page: int
    chunk_type: str      # 'text' or 'table'
    content: str


def chunk_prefix(company: str, fiscal_year: int | None, page: int) -> str:
    year = f" FY{fiscal_year}" if fiscal_year else ""
    return f"{company}{year}, page {page}:\n"


def _split_long(text: str, max_chars: int) -> list[str]:
    """Split one over-long paragraph at sentence ends (or spaces) into pieces <= max_chars."""
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        while len(sentence) > max_chars:   # a single huge "sentence": cut at the last space
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            pieces.append(sentence[:cut])
            sentence = sentence[cut:].lstrip()
        if current and len(current) + 1 + len(sentence) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def _pack_paragraphs(text: str, max_chars: int, overlap: int) -> list[str]:
    paragraphs = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if para:
            paragraphs.extend(_split_long(para, max_chars) if len(para) > max_chars else [para])

    chunks, current = [], ""
    for para in paragraphs:
        if current and len(current) + 2 + len(para) > max_chars:
            chunks.append(current)
            tail = current[-overlap:]
            tail = tail[tail.find(" ") + 1:] if " " in tail else tail   # start the overlap on a word
            current = f"{tail}\n\n{para}" if overlap else para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


def _split_table(markdown: str, max_chars: int) -> list[str]:
    if len(markdown) <= max_chars:
        return [markdown]
    lines = markdown.splitlines()
    header, rows = lines[:2], lines[2:]   # Markdown tables: header row + |---| separator
    pieces, current = [], list(header)
    for row in rows:
        if len(current) > 2 and sum(len(l) + 1 for l in current) + len(row) > max_chars:
            pieces.append("\n".join(current))
            current = list(header)
        current.append(row)
    pieces.append("\n".join(current))
    return pieces


def chunk_pages(pages: list[ParsedPage], company: str, fiscal_year: int | None,
                max_chars: int = 900, overlap: int = 150, max_table_chars: int = 2500) -> list[Chunk]:
    """Chunks for every page, in page order."""
    chunks = []
    for page in pages:
        prefix = chunk_prefix(company, fiscal_year, page.page)
        for table in page.tables:
            for piece in _split_table(table, max_table_chars):
                chunks.append(Chunk(page.page, "table", prefix + piece))
        for piece in _pack_paragraphs(page.text, max_chars, overlap):
            if len(piece.strip()) >= MIN_CONTENT_CHARS:
                chunks.append(Chunk(page.page, "text", prefix + piece))
    return chunks
