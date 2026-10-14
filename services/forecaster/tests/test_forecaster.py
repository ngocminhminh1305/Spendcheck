from datetime import date

import pytest

from app.features import summarise
from app.forecaster import budget_risk, predict


def test_pace_extrapolates_current_rate():
    # $100 in 10 days of a 30-day month -> $300
    assert predict("pace", [], 100, 10, 30) == 300


def test_blend_adds_usual_rate_for_remaining_days():
    # spent 100 so far; usual month is 300; 20 of 30 days left -> 100 + 200
    assert predict("blend", [300, 300, 300], 100, 10, 30) == 300


def test_no_history_falls_back_to_pace():
    assert predict("three_month_avg", [], 50, 5, 30) == 300


def test_unknown_method_raises():
    with pytest.raises(ValueError):
        predict("magic", [], 0, 1, 30)


def test_budget_alert():
    assert budget_risk(500, [], budget=400)["alert"] is True
    assert budget_risk(300, [], budget=400)["alert"] is False
    assert budget_risk(300, [])["alert"] is False  # no history, no budget


def test_summarise_fills_empty_months_and_ignores_future():
    tx = [
        (date(2026, 7, 3), 100.0),
        # August: nothing spent
        (date(2026, 9, 1), 40.0),
        (date(2026, 9, 10), 60.0),
        (date(2026, 9, 25), 999.0),  # after as_of: must be ignored
    ]
    s = summarise(tx, as_of=date(2026, 9, 15))
    assert s.history == [100.0, 0.0]
    assert s.spent_so_far == 100.0
    assert (s.days_elapsed, s.days_in_month) == (15, 30)


STEADY = [1000.0, 1100.0, 900.0, 1050.0, 950.0, 1000.0, 1020.0, 980.0]


def test_arima_and_prophet_forecast_near_steady_level():
    for method in ("arima", "prophet"):
        f = predict(method, STEADY, 0, 15, 30, month="2026-10")
        assert 800 < f < 1200, (method, f)


def test_arima_and_prophet_fall_back_with_short_history():
    # 3 months < MIN_FIT_MONTHS -> three_month_avg
    for method in ("arima", "prophet"):
        assert predict(method, [100, 200, 300], 0, 15, 30, month="2026-10") == 200


def test_prophet_needs_month():
    with pytest.raises(ValueError):
        predict("prophet", STEADY, 0, 15, 30)

def test_arima_blend_adds_arima_rate_for_remaining_days():
    # Half the month gone, $500 spent, ARIMA expects ~$1,000/month
    # -> 500 + ~1,000 x 15/30 = ~1,000
    f = predict("arima_blend", STEADY, 500, 15, 30, month="2026-10")
    assert 900 < f < 1100

def test_arima_blend_falls_back_to_blend_with_short_history():
    history = [300,300,300]
    a = predict("arima_blend", history, 500, 15, 30, month = "2026-10")
    b = predict("blend", history, 500, 15, 30, month = "2026-10")
    assert a == b

def test_arima_blend_differs_from_blend():
    # Last 3 months jumped to 2000; ARIMA pulls back toward the long-run
    # level, the 3-month average doesn't -> the two must disagree
    history = [1000] * 6 + [2000] * 3
    a = predict("arima_blend", history, 500, 15, 30)
    b = predict("blend", history, 500, 15, 30)
    assert a != b
