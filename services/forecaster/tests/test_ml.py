import math

import pytest

from app.forecaster import predict
from app.ml_features import FEATURES, make_features
from app.ml_model import MODEL_PATH

needs_model = pytest.mark.skipif(not MODEL_PATH.exists(),
                                 reason="train first: python -m scripts.train")


def test_features_are_scale_free():
    # Same spending pattern in SGD and in CZK (x100) -> identical features
    sgd = make_features([300, 320, 280, 310], 150, 15, 30, "2026-10")
    czk = make_features([30000, 32000, 28000, 31000], 15000, 15, 30, "2026-10")
    assert sgd == czk


def test_features_have_every_column_and_mark_missing_as_nan():
    f = make_features([300, 300, 300], 100, 10, 30)
    assert list(f) == FEATURES
    assert math.isnan(f["avg12"]) and math.isnan(f["month_of_year"])


def test_no_usual_level_gives_none():
    assert make_features([], 100, 10, 30) is None
    assert make_features([500, 0, 0, 0], 100, 10, 30) is None


@needs_model
def test_ml_forecast_is_sensible():
    f = predict("ml", [1000.0] * 12, 500, 15, 30, month="1998-05")
    assert 700 < f < 1500


@needs_model
def test_ml_never_below_spent_so_far():
    assert predict("ml", [100.0] * 12, 5000, 15, 30, month="1998-05") >= 5000


@needs_model
def test_ml_falls_back_to_blend_without_history():
    h = [500, 0, 0, 0]  # nothing spent in last 3 months -> no usual level
    assert predict("ml", h, 100, 10, 30) == predict("blend", h, 100, 10, 30)
