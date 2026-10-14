"""Backtest the forecasters on the Berka dataset.

For every account and every TEST month, stand on day --day of that month,
forecast the month's total with each method, and compare against the real
total. Only data up to that day is used, so nothing from the future leaks in.

Usage (from the forecaster/ folder):
    # fast methods, all accounts
    python -m scripts.evaluate_berka --day 15
    # include ARIMA + Prophet on a sample (Prophet is ~0.5s per forecast)
    python -m scripts.evaluate_berka --day 15 --methods all --accounts 500
"""

import argparse
import os
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path

import pandas as pd

from app.forecaster import METHODS, budget_risk, predict

FAST_METHODS = ["last_month", "three_month_avg", "pace", "blend", "ml"]
MIN_HISTORY = 3
# Berka transaction types: PRIJEM = money in, VYDAJ / VYBER = money out.
SPEND_TYPES = ["VYDAJ", "VYBER"]


def load_spending(path: Path) -> pd.DataFrame:
    tx = pd.read_csv(path, sep=";", low_memory=False,
                     usecols=["account_id", "date", "type", "amount"])
    tx = tx[tx["type"].isin(SPEND_TYPES)].copy()
    tx["date"] = pd.to_datetime(tx["date"].astype(str), format="%y%m%d")
    tx["month"] = tx["date"].dt.to_period("M")
    return tx


def monthly_tables(tx: pd.DataFrame, day: int) -> tuple[pd.Series, pd.Series]:
    """Per (account, month): the full-month total, and the total up to `day`."""
    monthly = tx.groupby(["account_id", "month"])["amount"].sum()
    mtd = (tx[tx["date"].dt.day <= day]
           .groupby(["account_id", "month"])["amount"].sum()
           .reindex(monthly.index, fill_value=0.0))
    return monthly, mtd


def backtest_account(job, day: int, methods: list[str], test_from: pd.Period) -> list[dict]:
    """All forecasts for one account. Runs in a worker process."""
    acc, totals, so_far = job
    months = pd.period_range(totals.index.min(), totals.index.max(), freq="M")
    totals = totals.reindex(months, fill_value=0.0).to_numpy()
    so_far = so_far.reindex(months, fill_value=0.0).to_numpy()

    rows = []
    for i in range(MIN_HISTORY, len(months)):
        if months[i] < test_from:
            continue  # this month is only used as history, never scored
        history = totals[:i].tolist()
        dim = months[i].days_in_month
        elapsed = min(day, dim)
        row = {"account_id": acc, "month": str(months[i]),
               "months_of_history": i, "actual": totals[i]}
        for m in methods:
            row[m] = predict(m, history, so_far[i], elapsed, dim, month=str(months[i]))
        if "blend" in methods:
            # Was this month actually unusually high? (ground truth for the alert)
            row["overspent"] = totals[i] > budget_risk(0, history)["reference"]
            row["alert"] = budget_risk(row["blend"], history)["alert"]
        rows.append(row)
    return rows


def backtest(tx, day, methods, test_from, n_accounts=None, workers=1, seed=0):
    monthly, mtd = monthly_tables(tx, day)
    accounts = monthly.index.get_level_values(0).unique()
    if n_accounts:
        accounts = pd.Series(accounts).sample(n_accounts, random_state=seed)
    jobs = [(acc, monthly.xs(acc), mtd.xs(acc)) for acc in accounts]

    run = partial(backtest_account, day=day, methods=methods, test_from=test_from)
    if workers == 1:
        results = map(run, jobs)
    else:
        # Each account is independent, so spread them across CPU cores.
        pool = ProcessPoolExecutor(max_workers=workers)
        results = pool.map(run, jobs, chunksize=max(1, len(jobs) // (workers * 4)))
    rows = [row for acc_rows in results for row in acc_rows]
    if workers != 1:
        pool.shutdown()
    return pd.DataFrame(rows)


def report(res: pd.DataFrame, methods: list[str]) -> None:
    print(f"\n{len(res):,} account-months, {res['account_id'].nunique():,} accounts")
    print(f"test months {res['month'].min()} to {res['month'].max()}\n")
    print("MAE by method (lower is better, CZK):")
    for m in methods:
        print(f"  {m:<16} {(res[m] - res['actual']).abs().mean():>10,.0f}")

    short = (res["months_of_history"] < 6).mean()
    if short and {"arima", "prophet", "arima_blend"} & set(methods):
        print(f"  ({short:.1%} of rows had <6 months history: arima/prophet fell "
              "back to three_month_avg, arima_blend to blend)")

    if "alert" in res:
        tp = (res["alert"] & res["overspent"]).sum()
        precision = tp / max(res["alert"].sum(), 1)
        recall = tp / max(res["overspent"].sum(), 1)
        print(f"\nRisk alert (blend): precision {precision:.2f}, recall {recall:.2f}")
        print(f"  overspend months: {res['overspent'].mean():.1%} of all months")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("data/raw/trans.csv"))
    ap.add_argument("--day", type=int, default=15, help="day of month we forecast from")
    ap.add_argument("--methods", default="fast",
                    help='"fast" (default), "all", or comma list e.g. blend,arima')
    ap.add_argument("--test-from", default="1998-01",
                    help="only score months from here on (earlier = history only)")
    ap.add_argument("--accounts", type=int, help="random sample of N accounts")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=Path("data/results"))
    args = ap.parse_args()

    methods = {"fast": FAST_METHODS, "all": list(METHODS)}.get(
        args.methods, args.methods.split(","))
    res = backtest(load_spending(args.data), args.day, methods,
                   pd.Period(args.test_from, freq="M"), args.accounts,
                   args.workers, args.seed)
    report(res, methods)

    args.out.mkdir(parents=True, exist_ok=True)
    tag = f"day{args.day}" + (f"_n{args.accounts}" if args.accounts else "")
    out_file = args.out / f"backtest_{tag}.csv"
    res.to_csv(out_file, index=False)
    print(f"\nPer-row results saved to {out_file}")
