"""Load the trained ML forecaster and use it to predict."""

from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

from app.ml_features import FEATURES, make_features, usual_level

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "forecaster_ml.joblib"


@lru_cache(maxsize=1)  # load from disk once, then reuse for every request
def load_model():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"{MODEL_PATH} not found. Train it first: python -m scripts.train")
    bundle = joblib.load(MODEL_PATH)
    if bundle["features"] != FEATURES:
        raise RuntimeError("Model was trained with different features. Retrain it.")
    return bundle["model"]


def ml_forecast(history, spent_so_far, days_elapsed, days_in_month, month=None) -> float | None:
    """Forecast this month's total, or None if there's no usual level to scale by."""
    f = make_features(history, spent_so_far, days_elapsed, days_in_month, month)
    if f is None:
        return None
    x = np.array([[f[name] for name in FEATURES]], dtype=float)
    # One row is tiny: starting parallel threads costs ~10x more than the
    # prediction itself, so force single-threaded.
    with threadpool_limits(limits=1):
        ratio = float(load_model().predict(x)[0])
    # The month's total can never be less than what's already been spent.
    return max(ratio * usual_level(history), spent_so_far)
