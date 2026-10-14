"""FastAPI service for Module 3. Run with: uvicorn app.main:app --reload"""

from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI

from app.features import summarise
from app.forecaster import budget_risk, predict
from app.ml_model import load_model
from app.schemas import ForecastRequest, ForecastResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()  # load the ML model at startup, so the first request isn't slow
    yield


app = FastAPI(title="Spendcheck Module 3: Spending Forecaster", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/forecast", response_model=ForecastResponse)
def forecast(req: ForecastRequest):
    as_of = req.as_of or date.today()
    s = summarise([(t.date, t.amount) for t in req.transactions], as_of)

    total = predict(req.method, s.history, s.spent_so_far, s.days_elapsed,
                    s.days_in_month, month=as_of.strftime("%Y-%m"))
    risk = budget_risk(total, s.history, req.budget)

    return ForecastResponse(
        as_of=as_of,
        month=as_of.strftime("%Y-%m"),
        method=req.method,
        spent_so_far=round(s.spent_so_far, 2),
        forecast_total=round(total, 2),
        days_elapsed=s.days_elapsed,
        days_in_month=s.days_in_month,
        months_of_history=len(s.history),
        risk=risk,
    )
