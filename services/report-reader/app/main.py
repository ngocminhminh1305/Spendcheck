"""Module 5 HTTP API: SGX Report Reader.

Endpoints
    GET  /health         liveness
    GET  /ready          readiness: Postgres is reachable
    GET  /v1/documents   reports that have been ingested (for the UI's company list)
    POST /v1/ask         answer a question about a report, with page citations
Its main caller is Module 4's chat agent (search_annual_reports tool).
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from spendcheck_common import configure_logging, install_common_middleware
from spendcheck_common.llm import LLMError, build_llm

from . import answer, retriever, store
from .config import get_settings
from .embeddings import Embedder
from .schemas import AskRequest, AskResponse, DocumentInfo

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    app.state.pool = store.create_pool(settings.database_url)
    app.state.embedder = Embedder(settings.embedding_model, settings.embedding_cache_dir)
    app.state.llm, app.state.llm_error = None, None
    try:
        app.state.llm = build_llm()
    except Exception as exc:  # start anyway so /health and /v1/documents work
        log.warning("LLM client not configured: %s", exc)
        app.state.llm_error = str(exc)
    yield
    app.state.pool.close()


app = FastAPI(title="Spendcheck Module 5: SGX Report Reader", version="0.2.0", lifespan=lifespan)
install_common_middleware(app, service_name="report-reader")


@app.exception_handler(LLMError)
async def llm_error(request: Request, exc: LLMError):
    log.error("LLM call failed (status %s): %s", exc.status, exc)
    if exc.status == 429:
        return JSONResponse(status_code=429, content={
            "detail": "The AI model's rate limit was reached (free models: 20 per minute, 50 per day). Try again later."})
    return JSONResponse(status_code=502, content={"detail": f"AI service error: {exc}"})


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready(request: Request):
    if store.ping(request.app.state.pool):
        return {"status": "ready"}
    return JSONResponse(status_code=503, content={"status": "database unavailable"})


@app.get("/v1/documents", response_model=list[DocumentInfo])
def documents(request: Request) -> list[DocumentInfo]:
    return store.list_documents(request.app.state.pool)


@app.post("/v1/ask", response_model=AskResponse)
def ask(body: AskRequest, request: Request) -> AskResponse:
    # Annual reports are public, so no X-User-Id is needed here.
    state = request.app.state
    if state.llm is None:
        raise HTTPException(status_code=503, detail=f"AI model not configured: {state.llm_error}")
    settings = get_settings()
    chunks = retriever.retrieve(body, pool=state.pool, embedder=state.embedder, settings=settings)
    return answer.answer_question(body, chunks, llm=state.llm, settings=settings)
