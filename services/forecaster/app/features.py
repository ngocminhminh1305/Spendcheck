"""Turn a raw list of transactions into the inputs the forecaster needs."""

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass
class MonthSummary:
    history: list[float]  # past complete monthly totals, oldest -> newest
    spent_so_far: float
    days_elapsed: int
    days_in_month: int


def summarise(transactions: list[tuple[date, float]], as_of: date) -> MonthSummary:
    current = pd.Period(as_of, freq="M")
    summary = MonthSummary([], 0.0, as_of.day, current.days_in_month)
    if not transactions:
        return summary

    df = pd.DataFrame(transactions, columns=["date", "amount"])
    df["date"] = pd.to_datetime(df["date"])
    # Drop anything after as_of: the model must never see the future.
    df = df[df["date"] <= pd.Timestamp(as_of)]

    monthly = df.groupby(df["date"].dt.to_period("M"))["amount"].sum()
    summary.spent_so_far = float(monthly.get(current, 0.0))

    past = monthly[monthly.index < current]
    if not past.empty:
        # Months with no transactions must appear as 0, not be skipped.
        all_months = pd.period_range(past.index.min(), current - 1, freq="M")
        summary.history = past.reindex(all_months, fill_value=0.0).astype(float).tolist()
    return summary
