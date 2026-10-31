# API gateway

The website's single API. It calls the five modules, stores transactions and budgets in Postgres,
and returns everything the website shows. There is no login: every request acts as `DEMO_USER_ID`,
and the gateway passes that user to the modules in the `X-User-Id` header.

| Route | What it does |
|---|---|
| `GET /api/status` | which modules and the database are up (the M1 to M5 lights) |
| `GET /api/categories` | category names |
| `POST /api/entries/parse` | Module 1 then Module 2: a **draft** entry, nothing saved |
| `POST /api/transactions`, `GET /api/transactions`, `DELETE /api/transactions/{id}` | save a checked draft, list, remove |
| `GET /api/summary?month=` | spent, budget, totals by category and by day |
| `GET /api/forecast` | Module 3 on the user's transactions and this month's budget |
| `GET` / `PUT` / `DELETE /api/budgets` | the month's budgets (overall or per category) |
| `POST /api/chat` | Module 4, which calls Modules 3 and 5 itself |
| `GET /api/reports/documents` | the annual reports Module 5 has loaded |

Request and response shapes: `docs/CONTRACTS.md`, section 5, and the interactive docs at
http://localhost:8000/docs when the stack is running.

**Parse, then save.** `app/entries.py` asks Module 1 for amount, merchant and date, then Module 2
for the category. A missing date becomes today; a bare "Grab" with a destination ("grab to school
14.60") is asked again as "Grab ride"; an unfamiliar merchant's category below 0.5 confidence is
marked "please check". The website shows the draft, the user fixes anything flagged, and only then
is it saved, so a wrong guess never reaches the database.

**Tracing.** Each request gets an `X-Request-ID` that is forwarded to every module, and the
response carries a `Server-Timing` header with the time spent in each module.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | | Postgres, as the `spendcheck_app` role |
| `EXTRACTOR_URL`, `CATEGORISER_URL`, `FORECASTER_URL`, `CHAT_AGENT_URL`, `REPORT_READER_URL` | `http://<service>:8000` | the modules |
| `DEMO_USER_ID` | `demo-user` | the user every request acts as |
| `TIMEZONE` | `Asia/Singapore` | what "today" means |
| `CORS_ORIGINS` | `http://localhost:5173` | only for the Vite dev server; the built site is same-origin |

## Run and test

From the repo root: `docker compose up -d` starts it with everything else (host port 8000).

```bash
docker compose run --rm --no-deps -v "$PWD/services/gateway/tests:/app/tests:ro" gateway python -m unittest discover -s tests
```

In Git Bash, run `export MSYS_NO_PATHCONV=1` first.
