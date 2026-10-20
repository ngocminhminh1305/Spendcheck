"""Spendcheck integration change: one-off purchases are kept out of the spending pace."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.features import one_off_spend
from app.main import app

client = TestClient(app)


def daily(start: date, days: int, amount: float) -> list[dict]:
    return [{"date": (start + timedelta(days=i)).isoformat(), "amount": amount} for i in range(days)]


# Three normal months of $20 a day (~$600 a month), then 15 days of September.
HISTORY = daily(date(2026, 6, 1), 30, 20) + daily(date(2026, 7, 1), 30, 20) + daily(date(2026, 8, 1), 30, 20)
SEPTEMBER = daily(date(2026, 9, 1), 15, 20)
LAPTOP = {"date": "2026-09-06", "amount": 400}


def test_large_purchase_is_added_once_not_extrapolated():
    body = {"as_of": "2026-09-15", "method": "pace", "transactions": HISTORY + SEPTEMBER + [LAPTOP]}
    data = client.post("/forecast", json=body).json()
    assert data["spent_so_far"] == 700            # still reports everything spent
    assert data["one_off_spend"] == 400
    assert data["forecast_total"] == 1000          # pace on $300 everyday spend = 600, plus 400 once


def test_ordinary_purchases_are_not_one_offs():
    pairs = [(date.fromisoformat(t["date"]), t["amount"]) for t in HISTORY + SEPTEMBER]
    pairs.append((date(2026, 9, 10), 60.0))       # 3x a typical purchase: ordinary
    assert one_off_spend(pairs, date(2026, 9, 15), [600.0, 620.0, 600.0]) == 0.0


def test_no_history_means_no_one_offs():
    assert one_off_spend([(date(2026, 9, 2), 500.0)], date(2026, 9, 15), []) == 0.0
