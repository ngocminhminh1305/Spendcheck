"""Request and response bodies for the report reader API (the contract in docs/CONTRACTS.md)."""

from typing import Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000, examples=["What was DBS's net profit in 2024?"])
    # Optional filters. The UI can pass them from a dropdown; otherwise full mode tries to detect
    # the company and year from the question.
    doc_id: str | None = None
    company: str | None = None
    fiscal_year: int | None = None
    # "full" = our pipeline. "basic" = evaluation baseline from the proposal: the same LLM with
    # basic retrieval (dense top-k over every document, no filters, no grounded citations).
    mode: Literal["full", "basic"] = "full"
    top_k: int | None = Field(default=None, ge=1, le=20)


class Citation(BaseModel):
    doc_id: str
    company: str
    fiscal_year: int | None
    page: int                       # 1-based page in the PDF
    quote: str                      # the exact text the answer relies on


class RetrievedChunk(BaseModel):
    doc_id: str
    page: int
    chunk_type: Literal["text", "table", "page"]   # "page" = a whole page (full mode)
    score: float


class AskResponse(BaseModel):
    answer: str
    mode: Literal["full", "basic"]
    citations: list[Citation] = Field(default_factory=list)
    retrieved: list[RetrievedChunk] = Field(default_factory=list)   # for debugging and the eval
    model: str | None = None
    disclaimer: str = "Factual information from company reports only. Not investment advice."


class DocumentInfo(BaseModel):
    doc_id: str
    corpus: Literal["sgx", "financebench"]
    company: str
    ticker: str | None
    fiscal_year: int | None
    n_pages: int
