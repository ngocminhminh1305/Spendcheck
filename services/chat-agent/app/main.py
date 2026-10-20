"""Module 4 HTTP API: Budget Chat Agent.

Endpoints
    GET  /health    liveness: the process is up
    GET  /ready     readiness: Postgres is reachable
    POST /v1/chat   answer a question about the caller's spending or an SGX company
                    (X-User-Id header required)
"""

import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from spendcheck_common import configure_logging, install_common_middleware, require_user_id
from spendcheck_common.llm import LLMError, build_llm

from . import agent, baseline, db
from .config import get_settings
from .schemas import ChatRequest, ChatResponse

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    app.state.pool = db.create_pool(settings.database_url)
    app.state.llm, app.state.llm_error = None, None
    try:
        app.state.llm = build_llm()
    except Exception as exc:  # start anyway so /health works; /v1/chat explains what is missing
        log.warning("LLM client not configured: %s", exc)
        app.state.llm_error = str(exc)
    yield
    app.state.pool.close()


app = FastAPI(title="Spendcheck Module 4: Budget Chat Agent", version="0.2.0", lifespan=lifespan)
install_common_middleware(app, service_name="chat-agent")


@app.exception_handler(LLMError)
async def llm_error(request: Request, exc: LLMError):
    """The model could not be reached or rejected the call (bad key, rate limit, outage)."""
    log.error("LLM call failed (status %s): %s", exc.status, exc)
    if exc.status == 429:
        return JSONResponse(status_code=429, content={
            "detail": "The AI model's rate limit was reached (free models: 20 per minute, 50 per day). Try again later."})
    return JSONResponse(status_code=502, content={"detail": f"AI service error: {exc}"})


def resolve_today(x_eval_today: str | None = Header(default=None)) -> date:
    """Today's date in Singapore, or the X-Eval-Today header when EVAL_MODE is on."""
    settings = get_settings()
    if settings.eval_mode and x_eval_today:
        try:
            return date.fromisoformat(x_eval_today)
        except ValueError:
            raise HTTPException(status_code=400, detail="X-Eval-Today must be YYYY-MM-DD")
    return datetime.now(ZoneInfo(settings.timezone)).date()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready(request: Request):
    if db.ping(request.app.state.pool):
        return {"status": "ready"}
    return JSONResponse(status_code=503, content={"status": "database unavailable"})


@app.post("/v1/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    request: Request,
    user_id: str = Depends(require_user_id),
    today: date = Depends(resolve_today),
) -> ChatResponse:
    # Plain `def` (not async): FastAPI runs it in a worker thread, so slow LLM and DB calls do not
    # block other requests.
    llm = request.app.state.llm
    if llm is None:
        raise HTTPException(status_code=503, detail=f"AI model not configured: {request.app.state.llm_error}")
    deps = {"llm": llm, "pool": request.app.state.pool, "settings": get_settings(), "today": today}
    if body.mode == "baseline":
        return baseline.answer_from_pasted_history(body, user_id, **deps)
    return agent.run_agent(body, user_id, request.state.request_id, **deps)
