"""Train the ML forecaster on Berka and save it to models/forecaster_ml.joblib.

Training uses ONLY months before --test-from (default 1998-01), so the 1998
months that evaluate_berka.py scores are never seen during training.

Each training row = one account, one month, seen from one day of that month:
    inputs  = make_features(history, spent_so_far, day, ...)
    target  = actual month total / usual level   (a ratio, see ml_features.py)
We create rows for many days per month so the model works on any day.

Usage (from the forecaster/ folder):
    python -m scripts.train
"""

import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor

from app.ml_features import FEATURES, make_features, usual_level
from scripts.evaluate_berka import MIN_HISTORY, load_spending, monthly_tables

TRAIN_DAYS = range(1, 29, 3)  # 1, 4, 7, ..., 28
MAX_RATIO = 20  # cap extreme targets (e.g. usual spend near zero) so they can't dominate


def build_rows(tx: pd.DataFrame, test_from: pd.Period) -> tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for day in TRAIN_DAYS:
        monthly, mtd = monthly_tables(tx, day)
        for acc, totals in monthly.groupby(level=0):
            totals = totals.droplevel(0)
            months = pd.period_range(totals.index.min(), totals.index.max(), freq="M")
            totals = totals.reindex(months, fill_value=0.0).to_numpy()
            so_far = mtd.xs(acc).reindex(months, fill_value=0.0).to_numpy()

            for i in range(MIN_HISTORY, len(months)):
                if months[i] >= test_from:
                    break  # test period: never train on it
                history = totals[:i].tolist()
                dim = months[i].days_in_month
                f = make_features(history, so_far[i], min(day, dim), dim, str(months[i]))
                if f is None:
                    continue
                X.append([f[name] for name in FEATURES])
                y.append(min(totals[i] / usual_level(history), MAX_RATIO))
        print(f"  day {day:>2}: {len(y):,} rows so far")
    return np.array(X, dtype=float), np.array(y)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("data/raw/trans.csv"))
    ap.add_argument("--test-from", default="1998-01")
    ap.add_argument("--out", type=Path, default=Path("models/forecaster_ml.joblib"))
    args = ap.parse_args()

    print("Building training rows...")
    X, y = build_rows(load_spending(args.data), pd.Period(args.test_from, freq="M"))

    # absolute_error loss = the model directly minimises MAE, our evaluation metric.
    # Early stopping holds out 10% of rows and stops adding trees once they stop helping.
    model = HistGradientBoostingRegressor(
        loss="absolute_error",
        learning_rate=0.05,
        max_iter=500,
        max_leaf_nodes=31,
        early_stopping=True,
        validation_fraction=0.1,
        random_state=0,
    )
    print(f"Training on {len(y):,} rows, {len(FEATURES)} features...")
    model.fit(X, y)
    print(f"  stopped after {model.n_iter_} trees")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "model": model,
        "features": FEATURES,
        "trained_before": args.test_from,
        "sklearn_version": sklearn.__version__,
    }, args.out)
    print(f"Saved to {args.out}")
