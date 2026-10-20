"""Module 5 answer generation with verifiable page citations.

Full mode (our design): the retrieved chunks are numbered [S1], [S2], ... and the model must tag
each fact with the source it used. Our code, not the model, turns [S2] into a page number by
looking up chunk 2. The model can only point at text it was actually given, so every citation
names a real page and comes with the exact passage it relied on. This works with any LLM.

Basic mode (evaluation baseline): the chunks are pasted with their page numbers and the model is
asked to write "[p. N]" itself, the common approach. Citation accuracy shows how often that goes
wrong (e.g. a page that was never retrieved).
"""

import re

from spendcheck_common.llm import LLM

from .config import Settings
from .schemas import AskRequest, AskResponse, Citation, RetrievedChunk
from .store import ChunkHit

_BASE = """\
You explain listed companies' annual reports and filings to new investors.
Answer from the report extracts provided. When the question needs a ratio, a change or a
judgement (for example "is it capital-intensive?"), work it out from the figures in the extracts
and show the working in one line, e.g. "current ratio = current assets 12.0 / current
liabilities 8.0 = 1.5". Only say the extracts do not contain the answer when the figures needed
are really missing. Explain financial terms in plain English the first time you use them.
State facts only: never recommend buying, selling or holding a stock.
Keep answers short: two to six sentences.
"""
FULL_SYSTEM = _BASE + """
Each extract starts with a source label such as [S3]. After every fact you state, add the label of
the extract it came from, exactly in that form, e.g. "Net profit rose 12% [S3]." Never cite a label
that was not provided.
"""
BASIC_SYSTEM = _BASE + """
Each extract shows its page number. After every fact you state, cite the page like [p. 12].
"""
NOTHING_FOUND = ("I couldn't find any annual-report pages about that. Try naming the company and year, "
                 "e.g. \"What was DBS's net profit in 2025?\"")
REFUSED = "Sorry, I can't help with that. I can explain facts from the annual reports I have."

# Models use [..], or full-width 【..】 brackets; accept both.
_SOURCE_GROUP = re.compile(r"[\[【]((?:S\d+)(?:\s*[,;]\s*S?\d+)*)[\]】]")
_SOURCE_NUM = re.compile(r"\d+")
_PAGE_MARK = re.compile(r"[\[【(]p(?:age)?\.?\s*(\d+)(?:\s*[-,]\s*\d+)*[\]】)]", re.IGNORECASE)
_PREFIX_LINE = re.compile(r"^.*, page \d+:\n")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")
_TERM = re.compile(r"[a-z0-9$][a-z0-9.,%$]*")


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: text.rfind(" ", 0, limit)].rstrip() + " ..."


def passage(chunk: ChunkHit, limit: int = 300) -> str:
    """The chunk's text without its "Company FYxxxx, page n:" label, shortened for display."""
    return _shorten(_PREFIX_LINE.sub("", chunk.content, count=1).strip(), limit)


def _terms(text: str) -> set[str]:
    return {t.rstrip(".,") for t in _TERM.findall(text.lower())}


def best_quote(chunk: ChunkHit, answer: str, limit: int = 300) -> str:
    """The sentence (or table row) of the chunk that best supports the answer: the one sharing the
    most words with it, where shared numbers count triple."""
    body = _PREFIX_LINE.sub("", chunk.content, count=1).strip()
    sentences = [s.strip() for s in _SENTENCE_BREAK.split(body) if len(s.strip()) > 15] or [body]
    wanted = _terms(answer)

    def overlap(sentence: str) -> int:
        return sum(3 if any(ch.isdigit() for ch in t) else 1 for t in _terms(sentence) & wanted)

    return _shorten(max(sentences, key=overlap), limit)   # max keeps the first of equal scores


def _citation(chunk: ChunkHit, answer: str, page: int | None = None, quote: str | None = None) -> Citation:
    return Citation(doc_id=chunk.doc_id, company=chunk.company, fiscal_year=chunk.fiscal_year,
                    page=page or chunk.page, quote=best_quote(chunk, answer) if quote is None else quote)


def resolve_source_labels(text: str, chunks: list[ChunkHit]) -> tuple[str, list[Citation]]:
    """Turn [S2] / [S1, S3] labels into [p. N] and collect the cited chunks (full mode)."""
    cited: dict[int, ChunkHit] = {}

    def replace(match: re.Match) -> str:
        numbers = [int(n) for n in _SOURCE_NUM.findall(match.group(1))]
        valid = [n for n in numbers if 1 <= n <= len(chunks)]
        for n in valid:
            cited.setdefault(n, chunks[n - 1])
        pages = sorted({chunks[n - 1].page for n in valid})
        return f"[p. {', '.join(map(str, pages))}]" if pages else ""   # unknown labels are dropped

    answer = _SOURCE_GROUP.sub(replace, text)
    return answer, [_citation(c, answer) for c in cited.values()]


def parse_page_marks(text: str, chunks: list[ChunkHit]) -> list[Citation]:
    """Citations from "[p. N]" marks the model typed itself (basic mode). A page that was never
    retrieved is still recorded, with an empty quote, so the evaluation can count it as wrong."""
    citations, seen = [], set()
    for match in _PAGE_MARK.finditer(text):
        page = int(match.group(1))
        if page in seen or not chunks:
            continue
        seen.add(page)
        on_page = next((c for c in chunks if c.page == page), None)
        citations.append(_citation(on_page, text) if on_page else _citation(chunks[0], text, page=page, quote=""))
    return citations


def _extracts(chunks: list[ChunkHit], labelled: bool) -> str:
    parts = []
    for i, c in enumerate(chunks, start=1):
        head = f"[S{i}]" if labelled else f"--- {c.company} FY{c.fiscal_year}, page {c.page} ---"
        parts.append(f"{head}\n{passage(c, limit=10_000)}")
    return "\n\n".join(parts)


def answer_question(request: AskRequest, chunks: list[ChunkHit], *, llm: LLM, settings: Settings) -> AskResponse:
    """Generate the answer and its page citations from the retrieved chunks."""
    retrieved = [RetrievedChunk(doc_id=c.doc_id, page=c.page, chunk_type=c.chunk_type, score=c.score) for c in chunks]
    if not chunks:
        return AskResponse(answer=NOTHING_FOUND, mode=request.mode, model=llm.model)

    full = request.mode == "full"
    prompt = f"Report extracts:\n\n{_extracts(chunks, labelled=full)}\n\nQuestion: {request.question}"
    reply = llm.chat(system=FULL_SYSTEM if full else BASIC_SYSTEM,
                     messages=[{"role": "user", "content": prompt}],
                     max_tokens=settings.llm_max_tokens, effort=settings.llm_effort)
    if reply.stop == "refusal":
        return AskResponse(answer=REFUSED, mode=request.mode, retrieved=retrieved, model=llm.model)

    text = reply.text.strip()
    if full:
        answer, citations = resolve_source_labels(text, chunks)
    else:
        answer, citations = text, parse_page_marks(text, chunks)
    return AskResponse(answer=answer, mode=request.mode, citations=citations, retrieved=retrieved, model=llm.model)
