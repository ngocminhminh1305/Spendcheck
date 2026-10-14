"""Core forecasting logic.

Simple methods live here as plain arithmetic; ARIMA and Prophet live in
ts_models.py. predict() is the ONE entry point for all of them, so the API and
the Berka evaluation script share exactly the same model code.

Every method answers one question: standing on `as_of` (some day in the
current month), what will this month's TOTAL spending be?

Inputs every method receives:
    history        past complete monthly totals, oldest -> newest
    spent_so_far   spending from day 1 of this month up to and including as_of
    days_elapsed   day-of-month of as_of (1..31)
    days_in_month  28..31
    month          the month being forecast, "YYYY-MM" (only Prophet uses it)
"""

from statistics import mean

METHODS = ("last_month", "three_month_avg", "pace", "blend", "arima", "prophet", "arima_blend", "ml")


def predict(
    method: str,
    history: list[float],
    spent_so_far: float,
    days_elapsed: int,
    days_in_month: int,
    month: str | None = None,
) -> float:
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}, choose from {METHODS}")

    # Pace: "keep spending at the rate you have so far this month".
    pace = spent_so_far / days_elapsed * days_in_month

    # With no past months, pace is the only thing we can compute.
    if method == "pace" or not history:
        return pace

    if method == "last_month":
        return history[-1]

    avg3 = mean(history[-3:])
    if method == "three_month_avg":
        return avg3

    if method in ("arima", "prophet"):
        # Imported here, not at the top, because Prophet is slow to load and
        # the simple methods shouldn't pay for it.
        from app import ts_models

        if len(history) < ts_models.MIN_FIT_MONTHS:
            return avg3  # too little history to fit; use the closest simple method
        if method == "arima":
            return ts_models.arima_forecast(history)
        if month is None:
            raise ValueError("prophet needs the month being forecast")
        return ts_models.prophet_forecast(history, month)

    # Blend: what you've already spent is known for certain; for the days that
    # are left, assume you spend at your usual (3-month average) daily rate.
    remaining_share = (days_in_month - days_elapsed) / days_in_month
    if method == "arima_blend":
        from app import ts_models
        if len(history) >= ts_models.MIN_FIT_MONTHS:
            return spent_so_far + ts_models.arima_forecast(history) * remaining_share
        
    if method == "ml":
        # Trained gradient-boosting model (scripts/train.py). Falls through to
        # blend when the user has no usual spending level to scale by.
        from app.ml_model import ml_forecast

        forecast = ml_forecast(history, spent_so_far, days_elapsed, days_in_month, month)
        if forecast is not None:
            return forecast

    return spent_so_far + avg3 * remaining_share


def budget_risk(
    forecast: float,
    history: list[float],
    budget: float | None = None,
    tolerance: float = 1.1,
) -> dict:
    """Decide whether to warn the user.

    If the user set a budget, compare against it. Otherwise compare against
    their "usual level": 3-month average plus a 10% tolerance.
    """
    if budget is not None:
        reference, source = budget, "budget"
    elif history:
        reference, source = mean(history[-3:]) * tolerance, "usual_level"
    else:
        return {"alert": False, "reference": None, "source": None,
                "reason": "not enough history to judge risk"}

    alert = forecast > reference
    if alert:
        reason = f"forecast {forecast:.2f} exceeds {source} {reference:.2f}"
    else:
        reason = f"forecast {forecast:.2f} is within {source} {reference:.2f}"
    return {"alert": alert, "reference": round(reference, 2), "source": source,
            "reason": reason}
