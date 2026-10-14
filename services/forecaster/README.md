# Spendcheck — Module 3: Spending Forecaster

Forecast a user's end-of-month spending from their categorised transactions
(output of Modules 1 + 2) and raise a budget-risk alert, so users see a
shortfall *before* it happens.

Pipeline: categorised transactions → monthly history + month-to-date spend →
forecast (gradient-boosting model, with simple fallbacks) → budget-risk alert → JSON.

## Layout

```
app/
  main.py          FastAPI app: GET /health, POST /forecast
  schemas.py       request/response models (the API contract)
  features.py      transactions -> history, spent_so_far, days elapsed
  forecaster.py    predict(): single entry point for every method + budget-risk rule
  ts_models.py     ARIMA and Prophet (fit per user on past monthly totals)
  ml_features.py   features for the ML model (shared by training and the API)
  ml_model.py      loads the trained model and predicts
models/
  forecaster_ml.joblib   trained model (committed; rebuild with scripts/train.py)
scripts/
  train.py             train the ML model on Berka (months before 1998)
  evaluate_berka.py    backtest every method on Berka 1998, report MAE
data/              see data/README.md (Berka not committed)
tests/
```

## Methods

| method             | forecast of this month's total                                  |
|--------------------|-----------------------------------------------------------------|
| `last_month`       | last month's total                                              |
| `three_month_avg`  | average of the last 3 complete months                           |
| `pace`             | spent so far ÷ days elapsed × days in month                     |
| `blend`            | spent so far + 3-month average × share of month left            |
| `arima`            | ARIMA(1,0,0) fitted on the user's monthly totals                |
| `prophet`          | Prophet trend (+ yearly pattern if ≥26 months history)          |
| `arima_blend`      | spent so far + ARIMA forecast × share of month left             |
| **`ml`** (default) | gradient-boosting model trained across all Berka accounts       |

Fallbacks: `arima`/`prophet` need ≥6 months of history, otherwise they use
`three_month_avg`; `arima_blend` uses `blend`; `ml` uses `blend` when the user
has no spending in the last 3 months. With no history at all, every method uses `pace`.

Risk alert: forecast > user's budget, or, if no budget, > 1.1 × 3-month average.

### The ML model

- **Model:** scikit-learn `HistGradientBoostingRegressor`, `loss="absolute_error"`
  so it directly minimises MAE, the evaluation metric.
- **Training rows:** one per account × month × forecast day (days 1, 4, ..., 28),
  ~1.07M rows from 1993–1997. 1998 is never seen in training.
- **Scale-free:** every money feature is divided by the user's 3-month average and
  the model predicts the *ratio* actual / 3-month average. The same pattern in SGD
  or CZK gives the same features, so a model trained on Czech data can serve
  Singapore users.
- **Features (13):** share of month elapsed, spent so far, pace, each of the last
  3 months, 6- and 12-month averages, volatility of the last 6 months, same month
  last year, share of zero-spend months, months of history, month of year.
- **Constraint:** the forecast is never below what has already been spent.

## API

`POST /forecast` (`method` and `budget` are optional; `as_of` defaults to today)

```json
{
  "as_of": "2026-10-14",
  "transactions": [
    {"date": "2026-07-03", "amount": 300, "merchant": "FairPrice", "category": "Groceries"},
    {"date": "2026-08-03", "amount": 350, "merchant": "FairPrice", "category": "Groceries"},
    {"date": "2026-09-03", "amount": 320, "merchant": "Chagee", "category": "Food"},
    {"date": "2026-10-02", "amount": 180, "merchant": "Grab", "category": "Transport"}
  ]
}
```

Response:

```json
{
  "as_of": "2026-10-14", "month": "2026-10", "method": "ml",
  "spent_so_far": 180.0, "forecast_total": 327.96,
  "days_elapsed": 14, "days_in_month": 31, "months_of_history": 3,
  "risk": {"alert": false, "reference": 355.67, "source": "usual_level",
           "reason": "forecast 327.96 is within usual_level 355.67"}
}
```

Interactive docs at `/docs` once the server is running.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (or: source .venv/bin/activate)
pip install -r requirements-dev.txt
pytest
uvicorn app.main:app --reload   # then open http://localhost:8000/docs
```

## Run with Docker

```bash
docker build --load -t spendcheck-forecaster .
docker run --rm -p 8003:8000 spendcheck-forecaster   # http://localhost:8003/docs
```

## Train and evaluate on Berka

Put `trans.csv` in `data/raw/` first (see `data/README.md`).

```bash
python -m scripts.train                                   # ~3.5 min
python -m scripts.evaluate_berka --day 15                 # fast methods + ml, all accounts
python -m scripts.evaluate_berka --day 15 --methods all --accounts 500   # incl. ARIMA/Prophet
```

Every method is scored on all account-months in 1998, forecasting from a given
day of the month using only data up to that day.

## Results

MAE in CZK (lower is better), all 4,488 accounts, 1998:

| forecast made on | last_month | three_month_avg | pace   | blend | **ml**    |
|------------------|-----------:|----------------:|-------:|------:|----------:|
| day 5            | 10,675     | 9,355           | 20,862 | 8,579 | **6,862** |
| day 15           | 10,675     | 9,355           | 11,349 | 7,531 | **4,986** |
| day 25           | 10,675     | 9,355           | 4,230  | 3,804 | **2,270** |

All methods, day 15, same 500-account sample:

| method          | MAE       |
|-----------------|----------:|
| last_month      | 10,067    |
| pace            | 10,784    |
| prophet         | 9,077     |
| three_month_avg | 8,870     |
| arima           | 8,036     |
| blend           | 7,041     |
| arima_blend     | 6,843     |
| **ml**          | **4,694** |

`arima_blend` beats `blend` consistently (3 random samples at day 15: −2.3% to −2.8%;
day 5: −6.0%; day 25: −0.7%). The gain shrinks later in the month because ARIMA
only predicts the part of the month still to come.

Risk alert (blend-based): precision 0.54, recall 0.78 at day 15; recall only 0.31 at day 5.

## Limitations

- Berka is a 1990s Czech bank: ~17% of spending is recurring household bills
  (`SIPO`), unlike student spending in Singapore. The scale-free features help,
  but transfer to Singapore users is untested.
- Berka has no merchant categories, so forecasts are for total spend only.
- The risk alert is still a simple threshold on the forecast.

## Roadmap

- [x] Baselines on real Berka: last month, 3-month average, pace, blend
- [x] ARIMA and Prophet (proposal baselines), arima_blend
- [x] Gradient-boosting model, beats every baseline on days 5/15/25
- [ ] Risk alert based on the ML model; measure early-month recall
- [ ] Per-category forecasts (for Module 4 chat agent)
- [ ] Add service to team docker-compose
