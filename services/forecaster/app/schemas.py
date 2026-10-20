"""Request/response shapes for the API. FastAPI validates input against these."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class Transaction(BaseModel):
    # Matches what Module 1 (amount/merchant/date) + Module 2 (category) produce.
    date: date
    amount: float = Field(gt=0, description="Spend amount, positive")
    merchant: str | None = None
    category: str | None = None


class ForecastRequest(BaseModel):
    transactions: list[Transaction]
    as_of: date | None = Field(None, description="Defaults to today")
    budget: float | None = Field(None, gt=0, description="Monthly budget, optional")
    method: Literal["last_month", "three_month_avg", "pace", "blend", "arima", "prophet", "arima_blend", "ml"] = "ml"


class Risk(BaseModel):
    alert: bool
    reference: float | None
    source: Literal["budget", "usual_level"] | None
    reason: str


class ForecastResponse(BaseModel):
    as_of: date
    month: str
    method: str
    spent_so_far: float
    forecast_total: float
    days_elapsed: int
    days_in_month: int
    months_of_history: int
    # Spendcheck integration change: this month's one-off purchases, included in forecast_total
    # but kept out of the spending pace. 0 when there are none.
    one_off_spend: float = 0.0
    risk: Risk
