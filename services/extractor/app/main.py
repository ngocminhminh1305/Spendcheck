"""HTTP entry point. Start with: python -m uvicorn app.main:app --reload."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.gliner_extractor import load_model as load_gliner
from app.layered import ModelUnavailableError

from app.pipeline import extract_transaction
from app.schemas import ExtractRequest, ExtractResponse
from app.spacy_extractor import load_model as load_spacy


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Spendcheck integration change: load spaCy and GLiNER at startup. Otherwise the first entry
    # that needs a model waits ~20 s while they load. Set EXTRACTOR_WARMUP=0 to skip (e.g. tests).
    if os.getenv("EXTRACTOR_WARMUP", "1") == "1":
        try:
            load_spacy()
            load_gliner()
        except Exception:   # rules still work; requests that need a model will return 503
            logging.getLogger(__name__).exception("Model warm-up failed")
    yield


app = FastAPI(
    title="Spendcheck — Module 1",
    description="Local transaction extraction using rules, spaCy, and GLiNER.",
    version="1.0.0",
    lifespan=lifespan,
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
