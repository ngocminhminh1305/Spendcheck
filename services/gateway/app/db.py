"""Database access for the gateway (role spendcheck_app, which may write transactions).

That role sees every user's rows, so every query here filters by user_id explicitly.
"""

from datetime import date
from decimal import Decimal

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .schemas import Budget, BudgetIn, CategoryTotal, DayTotal, Summary, Transaction, TransactionIn


def create_pool(database_url: str) -> ConnectionPool:
    return ConnectionPool(database_url, min_size=1, max_size=5, open=True, kwargs={"autocommit": True})


def ping(pool: ConnectionPool) -> bool:
    try:
        with pool.connection(timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def month_bounds(month: str) -> tuple[date, date]:
    """First day of the month and first day of the next month, for "YYYY-MM"."""
    year, mon = int(month[:4]), int(month[5:7])
    start = date(year, mon, 1)
    return start, (date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1))


def _f(value) -> float:
    return float(value) if isinstance(value, Decimal) else value


def ensure_user(pool: ConnectionPool, user_id: str) -> None:
    with pool.connection() as conn:
        conn.execute("INSERT INTO users (user_id, display_name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                     (user_id, user_id))


def categories(pool: ConnectionPool) -> list[str]:
    with pool.connection() as conn:
        return [r[0] for r in conn.execute("SELECT name FROM categories ORDER BY name")]


def insert_transaction(pool: ConnectionPool, user_id: str, t: TransactionIn) -> Transaction:
    with pool.connection() as conn:
        txn_id = conn.execute(
            "INSERT INTO transactions (user_id, txn_date, amount, merchant, category, category_confidence, raw_text, source) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'app') RETURNING txn_id",
            (user_id, t.date, t.amount, t.merchant, t.category, t.category_confidence, t.raw_text),
        ).fetchone()[0]
    return Transaction(txn_id=txn_id, **t.model_dump())


def delete_transaction(pool: ConnectionPool, user_id: str, txn_id: int) -> bool:
    with pool.connection() as conn:
        return conn.execute("DELETE FROM transactions WHERE user_id = %s AND txn_id = %s",
                            (user_id, txn_id)).rowcount == 1


def list_transactions(pool: ConnectionPool, user_id: str, month: str | None, limit: int) -> list[Transaction]:
    where, params = "user_id = %s", [user_id]
    if month:
        start, end = month_bounds(month)
        where += " AND txn_date >= %s AND txn_date < %s"
        params += [start, end]
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT txn_id, txn_date AS date, amount, merchant, category, raw_text, category_confidence "
            f"FROM transactions WHERE {where} ORDER BY txn_date DESC, txn_id DESC LIMIT %s",
            [*params, limit],
        )
        return [Transaction(**{k: _f(v) for k, v in row.items()}) for row in cur.fetchall()]


def transactions_for_forecast(pool: ConnectionPool, user_id: str, until: date) -> list[dict]:
    """Every transaction up to `until`, in the shape Module 3 expects."""
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT txn_date, amount, merchant, category FROM transactions "
            "WHERE user_id = %s AND txn_date <= %s ORDER BY txn_date", (user_id, until)).fetchall()
    return [{"date": d.isoformat(), "amount": float(a), "merchant": m, "category": c} for d, a, m, c in rows]


def budgets(pool: ConnectionPool, user_id: str, month: str) -> list[Budget]:
    start, _ = month_bounds(month)
    with pool.connection() as conn:
        rows = conn.execute("SELECT category, amount FROM budgets WHERE user_id = %s AND month = %s",
                            (user_id, start)).fetchall()
    return [Budget(month=month, category=c, amount=float(a)) for c, a in rows]


def upsert_budget(pool: ConnectionPool, user_id: str, b: BudgetIn) -> Budget:
    start, _ = month_bounds(b.month)
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO budgets (user_id, month, category, amount) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (user_id, month, category) DO UPDATE SET amount = EXCLUDED.amount",
            (user_id, start, b.category, b.amount))
    return Budget(**b.model_dump())


def delete_budget(pool: ConnectionPool, user_id: str, month: str, category: str | None) -> bool:
    start, _ = month_bounds(month)
    with pool.connection() as conn:
        return conn.execute(
            "DELETE FROM budgets WHERE user_id = %s AND month = %s AND category IS NOT DISTINCT FROM %s",
            (user_id, start, category)).rowcount == 1


def summary(pool: ConnectionPool, user_id: str, month: str) -> Summary:
    start, end = month_bounds(month)
    with pool.connection() as conn:
        by_cat = conn.execute(
            "SELECT category, SUM(amount) FROM transactions WHERE user_id = %s AND txn_date >= %s AND txn_date < %s "
            "GROUP BY category ORDER BY SUM(amount) DESC", (user_id, start, end)).fetchall()
        by_day = conn.execute(
            "SELECT txn_date, SUM(amount) FROM transactions WHERE user_id = %s AND txn_date >= %s AND txn_date < %s "
            "GROUP BY txn_date ORDER BY txn_date", (user_id, start, end)).fetchall()
        count = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE user_id = %s AND txn_date >= %s AND txn_date < %s",
            (user_id, start, end)).fetchone()[0]
    month_budgets = {b.category: b.amount for b in budgets(pool, user_id, month)}
    return Summary(
        month=month,
        spent=round(sum(float(a) for _, a in by_cat), 2),
        budget=month_budgets.get(None),
        transactions=count,
        by_category=[CategoryTotal(category=c, amount=float(a), budget=month_budgets.get(c)) for c, a in by_cat],
        by_day=[DayTotal(date=d, amount=float(a)) for d, a in by_day],
    )
