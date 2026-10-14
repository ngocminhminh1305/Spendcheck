"""Classic time-series models: ARIMA and Prophet.

Both fit a fresh model on ONE user's past monthly totals and forecast the next
month. Neither looks at this month's spending so far; that is what makes them
"history-only" baselines, like last_month and three_month_avg.
"""

import logging
import warnings

# Silence Prophet's chatty logging before importing it.
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
# prophet.plot logs "Importing plotly failed" at ERROR level; we never plot.
logging.getLogger("prophet.plot").setLevel(logging.CRITICAL)

import pandas as pd  # noqa: E402
from prophet import Prophet  # noqa: E402
from statsmodels.tsa.arima.model import ARIMA  # noqa: E402

# With fewer past months than this, fitting a model is meaningless.
MIN_FIT_MONTHS = 6


def arima_forecast(history: list[float]) -> float:
    """ARIMA(1,0,0) = "next month is pulled toward this month, and toward the
    long-run average". The simplest ARIMA that suits short, noisy series."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # convergence warnings on tiny series
        fit = ARIMA(history, order=(1, 0, 0)).fit()
    return max(float(fit.forecast(1)[0]), 0.0)


def prophet_forecast(history: list[float], month: str) -> float:
    """Prophet = trend + yearly seasonality. Needs real dates so it can learn
    e.g. "December is expensive", so we rebuild the month labels.

    month: the month being forecast, "YYYY-MM".
    """
    target = pd.Period(month, freq="M")
    months = pd.period_range(end=target - 1, periods=len(history), freq="M")
    df = pd.DataFrame({"ds": months.to_timestamp(), "y": history})

    model = Prophet(
        # Yearly pattern only with 2+ full years (25 monthly points span 730
        # days, which Prophet requires). Low Fourier order (3)
        # keeps it smooth so it can't overfit a handful of points.
        yearly_seasonality=3 if len(history) >= 26 else False,
        weekly_seasonality=False,
        daily_seasonality=False,
    )
    model.fit(df)
    yhat = model.predict(pd.DataFrame({"ds": [target.to_timestamp()]}))["yhat"].iloc[0]
    return max(float(yhat), 0.0)
