"""Create synthetic users with realistic Singapore spending, for Module 4's evaluation and demo.

    eval-user   fixed data from 1 Apr to 13 Oct 2026 (the evaluation's "today"). The random seed
                is fixed, so the data, and therefore every gold answer, is identical on every run.
    demo-user   the same kind of data for the six months up to the real today, for the live demo.

Run from the repo root with Postgres up:
    docker compose run --rm chat-eval python eval/seed_synthetic_user.py

Re-running replaces both users' data. No real person's data is involved (see proposal 3(c)).
"""

import math
import os
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg


@dataclass(frozen=True)
class Merchant:
    name: str
    category: str
    low: float          # typical price range in SGD
    high: float
    per_week: float     # average number of purchases per week


MERCHANTS = [
    Merchant("Kopitiam", "Food & Drink", 3.5, 7.5, 4.0),
    Merchant("Koufu", "Food & Drink", 4.0, 8.0, 2.5),
    Merchant("Chagee", "Food & Drink", 4.2, 6.8, 1.5),
    Merchant("McDonald's", "Food & Drink", 6.0, 13.0, 0.8),
    Merchant("Ya Kun Kaya Toast", "Food & Drink", 4.5, 8.5, 0.7),
    Merchant("Starbucks", "Food & Drink", 6.5, 9.5, 0.5),
    Merchant("Saizeriya", "Food & Drink", 9.0, 18.0, 0.3),
    Merchant("FairPrice", "Groceries", 6.0, 45.0, 1.2),
    Merchant("Sheng Siong", "Groceries", 8.0, 35.0, 0.4),
    Merchant("Cold Storage", "Groceries", 12.0, 50.0, 0.2),
    Merchant("Grab", "Transport", 9.0, 26.0, 1.0),
    Merchant("Gojek", "Transport", 8.0, 22.0, 0.4),
    Merchant("SimplyGo MRT", "Transport", 1.1, 2.4, 6.0),
    Merchant("Shopee", "Shopping", 6.0, 55.0, 0.6),
    Merchant("Lazada", "Shopping", 8.0, 70.0, 0.25),
    Merchant("Uniqlo", "Shopping", 19.9, 79.9, 0.12),
    Merchant("Daiso", "Shopping", 2.0, 14.0, 0.3),
    Merchant("Golden Village", "Entertainment", 13.0, 16.5, 0.3),
    Merchant("Teo Heng KTV", "Entertainment", 18.0, 36.0, 0.1),
    Merchant("Guardian", "Health", 4.0, 25.0, 0.25),
    Merchant("Watsons", "Health", 5.0, 30.0, 0.2),
    Merchant("Popular Bookstore", "Education", 4.0, 28.0, 0.15),
    Merchant("NUS Co-op", "Education", 5.0, 35.0, 0.1),
]

# Monthly charges: (merchant, category, amount, day of month)
SUBSCRIPTIONS = [
    ("Spotify", "Entertainment", 11.98, 5),
    ("Netflix", "Entertainment", 17.98, 12),
    ("Singtel", "Bills & Utilities", 32.90, 20),
]

# Occasional big purchases: (merchant, category, amount, days after the start date)
ONE_OFFS = [
    ("Scoot", "Travel", 248.00, 74),
    ("Agoda", "Travel", 186.40, 75),
    ("Polyclinic", "Health", 22.50, 124),
    ("Apple Store", "Shopping", 329.00, 173),
]

# Monthly budgets: None = overall budget for the month
BUDGETS = {None: 900, "Food & Drink": 350, "Transport": 120, "Shopping": 150}


def _poisson(rng: random.Random, lam: float) -> int:
    """Number of purchases on one day (Knuth's method; fine for small averages)."""
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _price(rng: random.Random, low: float, high: float) -> Decimal:
    return Decimal(str(round(rng.uniform(low, high) * 20) / 20)).quantize(Decimal("0.01"))  # nearest 5 cents


def generate(start: date, end: date, seed: int) -> list[tuple[date, Decimal, str, str]]:
    """Transactions (date, amount, merchant, category) for every day from start to end inclusive."""
    rng = random.Random(seed)
    rows = []
    day = start
    while day <= end:
        weekend = day.weekday() >= 5
        for m in MERCHANTS:
            rate = m.per_week / 7
            if weekend and m.category in ("Entertainment", "Shopping"):
                rate *= 1.6
            if weekend and m.name == "SimplyGo MRT":
                rate *= 0.4
            for _ in range(_poisson(rng, rate)):
                rows.append((day, _price(rng, m.low, m.high), m.name, m.category))
        for name, category, amount, dom in SUBSCRIPTIONS:
            if day.day == dom:
                rows.append((day, Decimal(f"{amount:.2f}"), name, category))
        day += timedelta(days=1)
    for name, category, amount, offset in ONE_OFFS:
        when = start + timedelta(days=offset)
        if when <= end:
            rows.append((when, Decimal(f"{amount:.2f}"), name, category))
    return sorted(rows)


def months_between(start: date, end: date) -> list[date]:
    months, m = [], start.replace(day=1)
    while m <= end:
        months.append(m)
        m = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
    return months


def seed_user(conn: psycopg.Connection, user_id: str, display_name: str, start: date, end: date, seed: int) -> None:
    rows = generate(start, end, seed)
    with conn.transaction():
        conn.execute("DELETE FROM users WHERE user_id = %s", (user_id,))   # cascades to their data
        conn.execute("INSERT INTO users (user_id, display_name) VALUES (%s, %s)", (user_id, display_name))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO transactions (user_id, txn_date, amount, merchant, category, raw_text, source) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'synthetic')",
                [(user_id, d, amt, merchant, cat, f"{merchant.lower()} {amt}") for d, amt, merchant, cat in rows],
            )
            cur.executemany(
                "INSERT INTO budgets (user_id, month, category, amount) VALUES (%s, %s, %s, %s)",
                [(user_id, month, cat, amt) for month in months_between(start, end) for cat, amt in BUDGETS.items()],
            )
    total = sum(r[1] for r in rows)
    print(f"{user_id}: {len(rows)} transactions from {start} to {end}, total ${total:,.2f}")


def main() -> None:
    url = os.environ["APP_DATABASE_URL"]   # spendcheck_app: the role allowed to write transactions
    today_sg = datetime.now(ZoneInfo("Asia/Singapore")).date()
    with psycopg.connect(url, autocommit=True) as conn:
        seed_user(conn, "eval-user", "Evaluation user", date(2026, 4, 1), date(2026, 10, 13), seed=2111)
        seed_user(conn, "demo-user", "Demo user", today_sg - timedelta(days=182), today_sg, seed=14)


if __name__ == "__main__":
    main()
