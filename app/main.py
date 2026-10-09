"""HTTP entry point. Start with: python -m uvicorn app.main:app --reload."""

import logging

from fastapi import FastAPI, HTTPException

from app.layered import ModelUnavailableError

from app.pipeline import extract_transaction
from app.schemas import ExtractRequest, ExtractResponse

app = FastAPI(
    title="Spendcheck — Module 1",
    description="Local transaction extraction using rules, spaCy, and GLiNER.",
    version="1.0.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    """A small endpoint to check that the local service is running."""
    return {"status": "ok"}


@app.post("/extract", response_model=ExtractResponse)
def extract(request: ExtractRequest) -> ExtractResponse:
    """Extract amount, merchant, and date from natural-language spending text."""
    try:
        return extract_transaction(request.text, request.reference_datetime)
    except ModelUnavailableError as exc:
        logging.getLogger(__name__).exception("Extraction model failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
