"""Spendcheck API gateway: the single entry point for the website.

    GET    /api/status                  which modules are up (status bar)
    GET    /api/categories              category names for dropdowns
    POST   /api/entries/parse           typed entry -> draft (Module 1 + Module 2), nothing saved
    POST   /api/transactions            save a confirmed draft
    GET    /api/transactions?month=     list, newest first
    DELETE /api/transactions/{id}       remove one
    GET    /api/summary?month=          totals by category and by day, plus budgets (dashboard)
    GET    /api/forecast                this month's forecast and risk alert (Module 3)
    GET    /api/budgets?month=          the month's budgets
    PUT    /api/budgets                 set a budget (overall or per category)
    DELETE /api/budgets?month=&category=  remove one
    POST   /api/chat                    the assistant (Module 4, which calls Module 5 itself)
    GET    /api/reports/documents       annual reports the assistant knows (Module 5)

There is no login: every request acts as DEMO_USER_ID. The gateway sets X-User-Id for the modules.
"""

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db
from .config import get_settings
from .entries import parse_entry
from .schemas import (JSON, Budget, BudgetIn, ChatRequest, Draft, ParseRequest, Status, Summary,
                      Transaction, TransactionIn)
from .services import ServiceError, Services, current_request_id, current_timings

log = logging.getLogger("gateway")
MONTH = Query(default=None, pattern=r"^\d{4}-\d{2}$", description="YYYY-MM, default: this month")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    logging.basicConfig(level=s.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app.state.pool = db.create_pool(s.database_url)
    app.state.services = Services(s)
    try:
        db.ensure_user(app.state.pool, s.demo_user_id)
    except Exception as exc:   # Postgres not up yet: /api/status will show it
        log.warning("could not ensure demo user: %s", exc)
    yield
    app.state.pool.close()


app = FastAPI(title="Spendcheck API gateway", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins.split(","),
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["Server-Timing", "X-Request-ID"])


@app.middleware("http")
async def timing(request: Request, call_next):
    """Request ID for tracing, plus a Server-Timing header with the time spent in each module."""
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    timings: list[tuple[str, float]] = []
    tokens = current_request_id.set(request_id), current_timings.set(timings)
    started = datetime.now()
    try:
        response = await call_next(request)
    finally:
        current_request_id.reset(tokens[0])
        current_timings.reset(tokens[1])
    total_ms = (datetime.now() - started).total_seconds() * 1000
    parts = [f"{name};dur={ms:.1f}" for name, ms in timings] + [f"total;dur={total_ms:.1f}"]
    response.headers["Server-Timing"] = ", ".join(parts)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(ServiceError)
async def service_error(request: Request, exc: ServiceError):
    log.error("%s: %s", exc.service, exc)
    return JSONResponse(status_code=502, content={"detail": str(exc), "service": exc.service})


def _now() -> datetime:
    return datetime.now(ZoneInfo(get_settings().timezone))


def _month(month: str | None) -> str:
    return month or _now().strftime("%Y-%m")


def _state(request: Request):
    return request.app.state.pool, request.app.state.services, get_settings().demo_user_id


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/status", response_model=Status)
def status(request: Request) -> Status:
    pool, services, user = _state(request)
    return Status(gateway=True, database=db.ping(pool), modules=services.health(),
                  demo_user=user, today=_now().date())


@app.get("/api/categories")
def categories(request: Request) -> list[str]:
    return db.categories(request.app.state.pool)


@app.post("/api/entries/parse", response_model=Draft)
def parse(body: ParseRequest, request: Request) -> Draft:
    _, services, _ = _state(request)
    return parse_entry(body.text, _now(), services)


@app.post("/api/transactions", response_model=Transaction, status_code=201)
def add_transaction(body: TransactionIn, request: Request) -> Transaction:
    pool, _, user = _state(request)
    if body.category not in db.categories(pool):
        raise HTTPException(status_code=400, detail=f"Unknown category {body.category!r}")
    return db.insert_transaction(pool, user, body)


@app.get("/api/transactions", response_model=list[Transaction])
def transactions(request: Request, month: str | None = MONTH, limit: int = Query(100, ge=1, le=1000)):
    pool, _, user = _state(request)
    return db.list_transactions(pool, user, month, limit)


@app.delete("/api/transactions/{txn_id}", status_code=204)
def remove_transaction(txn_id: int, request: Request) -> None:
    pool, _, user = _state(request)
    if not db.delete_transaction(pool, user, txn_id):
        raise HTTPException(status_code=404, detail="No such transaction")


@app.get("/api/summary", response_model=Summary)
def summary(request: Request, month: str | None = MONTH) -> Summary:
    pool, _, user = _state(request)
    return db.summary(pool, user, _month(month))


@app.get("/api/forecast")
def forecast(request: Request) -> JSON:
    pool, services, user = _state(request)
    today = _now().date()
    overall = next((b.amount for b in db.budgets(pool, user, today.strftime("%Y-%m")) if b.category is None), None)
    result = services.forecast(db.transactions_for_forecast(pool, user, today), today, overall)
    return {**result, "budget": overall}


@app.get("/api/budgets", response_model=list[Budget])
def budgets(request: Request, month: str | None = MONTH) -> list[Budget]:
    pool, _, user = _state(request)
    return db.budgets(pool, user, _month(month))


@app.put("/api/budgets", response_model=Budget)
def set_budget(body: BudgetIn, request: Request) -> Budget:
    pool, _, user = _state(request)
    if body.category is not None and body.category not in db.categories(pool):
        raise HTTPException(status_code=400, detail=f"Unknown category {body.category!r}")
    return db.upsert_budget(pool, user, body)


@app.delete("/api/budgets", status_code=204)
def remove_budget(request: Request, month: str = Query(pattern=r"^\d{4}-\d{2}$"), category: str | None = None) -> None:
    """Stop watching a category (or clear the overall budget when no category is given)."""
    pool, _, user = _state(request)
    if not db.delete_budget(pool, user, month, category):
        raise HTTPException(status_code=404, detail="No such budget")


@app.post("/api/chat")
def chat(body: ChatRequest, request: Request):
    _, services, user = _state(request)
    r = services.chat(user, body.model_dump())
    try:
        content = r.json()
    except ValueError:
        content = {"detail": r.text[:200]}
    return JSONResponse(status_code=r.status_code, content=content)   # keeps 429 / 503 from Module 4


@app.get("/api/reports/documents")
def documents(request: Request) -> list[JSON]:
    _, services, _ = _state(request)
    return services.documents()
