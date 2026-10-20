"""Turn a raw list of transactions into the inputs the forecaster needs."""

from dataclasses import dataclass
from datetime import date
from statistics import mean, median

import pandas as pd

# Spendcheck integration change: one-off purchases (see one_off_spend).
ONE_OFF_TYPICAL_MULTIPLE = 5   # at least 5x the user's typical (median) past purchase ...
ONE_OFF_MONTH_SHARE = 0.2      # ... and at least 20% of their usual (3-month average) month


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


def one_off_spend(transactions: list[tuple[date, float]], as_of: date, history: list[float]) -> float:
    """Spendcheck integration change: total of this month's unusually large single purchases.

    A $329 phone bought on day 6 is not a spending *pace*. Left in, it made the ML model (trained
    on Berka, where big payments are early-month bills) predict that the month was nearly over.
    The API forecasts everyday spending without these purchases and adds them back afterwards.
    """
    month_start = as_of.replace(day=1)
    past = [amount for d, amount in transactions if d < month_start]
    if not history or not past:
        return 0.0
    threshold = max(ONE_OFF_TYPICAL_MULTIPLE * median(past), ONE_OFF_MONTH_SHARE * mean(history[-3:]))
    return float(sum(amount for d, amount in transactions if month_start <= d <= as_of and amount >= threshold))
