"""Step 1 of ingestion: pull text and tables out of a PDF, page by page.

Page numbers are carried through every later step, because citations point to pages. They are
1-based PDF page numbers (what a PDF viewer shows), not the numbers printed on the pages.
"""

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import pymupdf

log = logging.getLogger(__name__)

_DIGITS = re.compile(r"\d+")
EDGE_LINES = 3   # running headers/footers live in the first and last few lines of a page


@dataclass
class ParsedPage:
    page: int                                          # 1-based
    text: str                                          # body text, paragraphs separated by blank lines
    tables: list[str] = field(default_factory=list)    # each table rendered as Markdown


def _line_key(line: str) -> str:
    """Normalise a line so "Annual Report 2025 | 57" and "... | 58" count as the same footer."""
    return _DIGITS.sub("#", line.strip().lower())


def _edge(n_lines: int) -> set[int]:
    """Indexes of the first and last EDGE_LINES lines of a page."""
    return set(range(min(EDGE_LINES, n_lines))) | set(range(max(0, n_lines - EDGE_LINES), n_lines))


def _tables_on(page: pymupdf.Page) -> tuple[list[pymupdf.Rect], list[str]]:
    """Detected tables as (bounding boxes, Markdown). Tiny or empty 'tables' are ignored."""
    try:
        found = page.find_tables().tables
    except Exception as err:   # table detection is best-effort; the numbers stay in the body text
        log.debug("table detection failed on page %d: %s", page.number + 1, err)
        return [], []
    rects, markdown = [], []
    for table in found:
        if table.row_count < 2 or table.col_count < 2:
            continue
        md = table.to_markdown().strip()
        if md:
            rects.append(pymupdf.Rect(table.bbox))
            markdown.append(md)
    return rects, markdown


def _read_pages(path: str) -> tuple[list[list[tuple[int, str]]], list[list[str]]]:
    """Per page: its text lines tagged with their block number, and its tables as Markdown."""
    pages_lines, pages_tables = [], []
    with pymupdf.open(path) as doc:
        for page in doc:
            table_rects, tables = _tables_on(page)
            lines = []
            for block_no, (x0, y0, x1, y1, text, _n, block_type) in enumerate(page.get_text("blocks", sort=True)):
                if block_type != 0:   # skip images
                    continue
                centre = pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2)
                if any(centre in rect for rect in table_rects):   # already captured as a table
                    continue
                lines.extend((block_no, line.strip()) for line in text.splitlines() if line.strip())
            pages_lines.append(lines)
            pages_tables.append(tables)
    return pages_lines, pages_tables


def parse_pdf(path: str) -> list[ParsedPage]:
    """Parse every page of the PDF at `path` into body text and Markdown tables.

    Running headers and footers (lines near the top or bottom that repeat on many pages, and bare
    page numbers there) are removed so they do not pollute every chunk.
    """
    pages_lines, pages_tables = _read_pages(path)

    edge_counts = Counter()
    for lines in pages_lines:
        edge_counts.update({_line_key(lines[i][1]) for i in _edge(len(lines))})
    threshold = max(3, int(0.4 * len(pages_lines)))

    pages = []
    for number, (lines, tables) in enumerate(zip(pages_lines, pages_tables), start=1):
        edge = _edge(len(lines))
        paragraphs: dict[int, list[str]] = defaultdict(list)
        for i, (block_no, line) in enumerate(lines):
            is_header_footer = i in edge and (
                line.isdigit() or (edge_counts[_line_key(line)] >= threshold and len(line) < 100))
            if not is_header_footer:
                paragraphs[block_no].append(line)
        # One paragraph per PDF text block; blank lines separate paragraphs for the chunker.
        text = "\n\n".join(" ".join(p) for _, p in sorted(paragraphs.items())).replace("\x00", "")
        if not text and not tables:
            log.info("page %d has no extractable text (scanned image?)", number)
        pages.append(ParsedPage(page=number, text=text, tables=tables))
    return pages
