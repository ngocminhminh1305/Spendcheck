"""Features for the ML forecaster.

Used by BOTH scripts/train.py and predict(), so the model always sees inputs
built exactly the same way in training and in the live API.

Scale-free design: every money feature is divided by the user's usual monthly
spend (`scale`), and the model predicts the RATIO actual / scale. A ratio of
1.3 means "30% above usual" whether the user spends 300 SGD or 30,000 CZK,
which is what lets a model trained on Czech Berka data serve Singapore users.
"""

import math
from statistics import mean, pstdev

FEATURES = [
    "day_frac",         # how far through the month we are (0..1)
    "mtd_ratio",        # spent so far / usual month
    "pace_ratio",       # pace forecast / usual month
    "last1", "last2", "last3",  # each of the last 3 months / usual month
    "avg6", "avg12",    # longer averages / usual month (shows trends)
    "volatility",       # std / mean of last 6 months: how erratic this user is
    "last_year",        # same month last year / usual month (seasonality)
    "zero_months",      # share of the last 6 months with no spending at all
    "months_of_history",
    "month_of_year",
]

MISSING = math.nan  # gradient boosting treats NaN as "unknown", no imputing needed


def usual_level(history: list[float]) -> float:
    """The scale every feature is divided by: mean of the last 3 months."""
    return mean(history[-3:]) if history else 0.0


def make_features(
    history: list[float],
    spent_so_far: float,
    days_elapsed: int,
    days_in_month: int,
    month: str | None = None,
) -> dict | None:
    """Return the feature dict, or None if the user has no usual level to
    scale by (no history, or spent nothing in the last 3 months)."""
    scale = usual_level(history)
    if scale <= 0:
        return None

    def ratio(i: int) -> float:  # history[-i] / scale, or NaN if too short
        return history[-i] / scale if len(history) >= i else MISSING

    last6 = history[-6:]
    return {
        "day_frac": days_elapsed / days_in_month,
        "mtd_ratio": spent_so_far / scale,
        "pace_ratio": spent_so_far / days_elapsed * days_in_month / scale,
        "last1": ratio(1),
        "last2": ratio(2),
        "last3": ratio(3),
        "avg6": mean(last6) / scale if len(history) >= 6 else MISSING,
        "avg12": mean(history[-12:]) / scale if len(history) >= 12 else MISSING,
        "volatility": pstdev(last6) / mean(last6) if len(last6) >= 3 and mean(last6) > 0 else MISSING,
        "last_year": ratio(12),
        "zero_months": sum(v == 0 for v in last6) / len(last6),
        "months_of_history": min(len(history), 60),
        "month_of_year": int(month[5:7]) if month else MISSING,
    }
