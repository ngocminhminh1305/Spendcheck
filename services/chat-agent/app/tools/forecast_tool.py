"""get_forecast tool: asks Module 3 for the user's predicted end-of-month spending.

Module 3 is stateless: it receives the transactions in the request instead of reading the
database. So this tool reads the user's own transactions and this month's budget (through the
same user-scoped, read-only connection as run_sql) and sends them to:

    POST {FORECASTER_URL}/forecast   {"transactions": [...], "as_of": "YYYY-MM-DD", "budget": 900}
"""

from datetime import date
from typing import Any

import httpx
import psycopg

TOOL_DEFINITION = {
    "name": "get_forecast",
    "description": (
        "Forecast the user's total spending for the CURRENT month with the forecasting model: "
        "amount spent so far, predicted end-of-month total, and a budget-risk alert compared with "
        "the user's monthly budget. Use it for questions about the rest of this month, "
        "affordability, or whether the user will overspend."
    ),
    "strict": True,
    "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
}


def load_inputs(conn: psycopg.Connection, today: date) -> tuple[list[dict], float | None]:
    """The user's transactions up to today and this month's overall budget."""
    rows = conn.execute(
        "SELECT txn_date, amount, merchant, category FROM transactions WHERE txn_date <= %s ORDER BY txn_date",
        (today,),
    ).fetchall()
    budget = conn.execute(
        "SELECT amount FROM budgets WHERE month = %s AND category IS NULL", (today.replace(day=1),)
    ).fetchone()
    transactions = [{"date": d.isoformat(), "amount": float(a), "merchant": m, "category": c} for d, a, m, c in rows]
    return transactions, float(budget[0]) if budget else None


def get_forecast(forecaster_url: str, transactions: list[dict], today: date, budget: float | None,
                 request_id: str | None = None) -> dict[str, Any]:
    """Call Module 3. Raises httpx.HTTPError if the forecaster is down or rejects the request."""
    headers = {"X-Request-ID": request_id} if request_id else {}   # one trace ID across services
    response = httpx.post(
        f"{forecaster_url}/forecast",
        json={"transactions": transactions, "as_of": today.isoformat(), "budget": budget},
        headers=headers,
        timeout=30.0,
    )
    response.raise_for_status()
    result = response.json()
    result["budget"] = budget
    return result
