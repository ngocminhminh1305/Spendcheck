# Spendcheck integration contracts

**Status: proposal.** Drafted by Okaggar (Modules 4 and 5) so all five modules can be built in
parallel and merged without surprises. Each owner confirms or edits their row at the next group
meeting; after that, changes go through a pull request that everyone sees.

## 1. Repository layout (one repo for the whole group)

```
spendcheck/
├── docker-compose.yml        local stack: every service + Postgres
├── .env.example              copy to .env for compose
├── db/init/                  shared schema (runs once on an empty database)
├── libs/common/              shared helpers: middleware, X-User-Id, Claude client
├── services/
│   ├── gateway/              public API for the frontend        (owner: ?)
│   ├── extractor/            Module 1  NLP entity extraction     (owner: ?)
│   ├── categoriser/          Module 2  merchant categoriser      (owner: ?)
│   ├── forecaster/           Module 3  spending forecaster       (owner: ?)
│   ├── chat-agent/           Module 4  budget chat agent         (owner: Okaggar)
│   └── report-reader/        Module 5  SGX report reader         (owner: Okaggar)
├── frontend/                 web UI                               (owner: ?)
├── k8s/                      Kubernetes manifests (kubectl apply -k k8s/)
└── docs/                     this file, module plans, report figures
```

Each service folder contains `Dockerfile`, `requirements.txt`, `app/` (FastAPI code),
optionally `eval/` (its evaluation scripts) and a short `README.md`.

## 2. Rules every service follows

1. **Python 3.12 + FastAPI**, one container per module, listening on **port 8000** inside the container.
2. **`GET /health`** (process is alive, no dependency checks) and **`GET /ready`** (dependencies
   such as the database are reachable). Kubernetes liveness/readiness probes call these.
3. Business endpoints live under **`/v1/...`**, take and return JSON defined with Pydantic models.
   Errors use normal HTTP status codes with FastAPI's `{"detail": "..."}` body.
4. **User identity comes from the `X-User-Id` header**, set only by the gateway. Services never
   read a user ID from the request body.
5. Forward **`X-Request-ID`** on every internal call. Installing the shared middleware does this and
   adds **`X-Process-Time-Ms`**, which the system-level latency evaluation reads:
   ```python
   from spendcheck_common import install_common_middleware
   install_common_middleware(app, service_name="forecaster")
   ```
6. **Configuration only through environment variables.** No secrets in images or in git.
7. **Build from the repo root:** `docker build -f services/<name>/Dockerfile .` (so `libs/common` is
   in the build context). Pin package versions in `requirements.txt`.
8. The **compose service name = Kubernetes Service name = hostname** other services use.

## 3. Service map

| Module | Service | Compose host port | In-cluster URL | Endpoints |
|---|---|---|---|---|
| Gateway | `gateway` | 8000 | `http://gateway:8000` | public `/api/*` (section 5) |
| 1 | `extractor` | 8001 | `http://extractor:8000` | `POST /extract` |
| 2 | `categoriser` | 8002 | `http://categoriser:8000` | `POST /classify` |
| 3 | `forecaster` | 8003 | `http://forecaster:8000` | `POST /forecast` |
| 4 | `chat-agent` | 8004 | `http://chat-agent:8000` | `POST /v1/chat` |
| 5 | `report-reader` | 8005 | `http://report-reader:8000` | `POST /v1/ask`, `GET /v1/documents` |
| DB | `postgres` | 5432 | `postgres:5432` | Postgres 16 + pgvector |
| UI | `frontend` | 3000 | `http://frontend:3000` | web app |

## 4. Endpoint contracts

Shapes for Modules 1 to 3 are **suggestions** for their owners to confirm; Module 4 depends on
Module 3's response, and the gateway depends on Modules 1 and 2.

### Module 1: `POST /extract` (implemented, team code in `services/extractor`)
```json
// request
{"text": "spent $8.90 at Kopitiam yesterday", "reference_datetime": "2026-10-06T18:30:00+08:00"}
// response
{"amount": 8.9, "merchant": "Kopitiam", "date": "2026-10-05", "status": "ok", "missing_fields": []}
```
`reference_datetime` must include a timezone offset; it resolves "yesterday" and makes results
repeatable. Fields it cannot extract confidently are `null`, with `status: "incomplete"` and the
names in `missing_fields`, so the UI can ask the user to fill them in. Model failures return 503.

### Module 2: `POST /classify` (implemented, team code in `services/categoriser`)
```json
// request: only the merchant; extra fields are rejected
{"merchant": "NTUC FairPrice"}
// response
{"category": "Groceries", "confidence": null, "source": "lookup", "model_version": "merchant-categoriser-v1"}
```
`source` is `lookup` (exact catalogue match, `confidence: null`) or `model` (MiniLM fallback,
uncalibrated probability). Nine categories: Food & Drink, Groceries, Transport, Shopping,
Entertainment, Bills & Utilities, Health, Education, Other. The database adds Travel for manual
entries. A bare "Grab" or "Apple" returns **422 ambiguous_merchant**; the gateway retries "<name>
ride" when the entry mentions a destination, otherwise the user picks the category.

### Module 3: `POST /forecast` (implemented, team code in `services/forecaster`)
```json
// request: the caller sends the user's transactions (Module 3 is stateless and has no DB access)
{"transactions": [{"date": "2026-09-03", "amount": 320, "merchant": "Chagee", "category": "Food & Drink"}],
 "as_of": "2026-10-14", "budget": 900, "method": "ml"}
// response
{"as_of": "2026-10-14", "month": "2026-10", "method": "ml", "spent_so_far": 180.0,
 "forecast_total": 327.96, "days_elapsed": 14, "days_in_month": 31, "months_of_history": 3,
 "risk": {"alert": false, "reference": 355.67, "source": "usual_level",
          "reason": "forecast 327.96 is within usual_level 355.67"}}
```
`as_of`, `budget` and `method` are optional (`method` defaults to the trained `ml` model). With a
budget the alert compares the forecast with it, otherwise with 1.1 x the 3-month average. Callers
(Module 4's `get_forecast` tool, the gateway) read the user's transactions and budget themselves.

### Module 4: `POST /v1/chat` (header `X-User-Id`)
```json
// request
{"message": "Can I afford a $300 concert ticket?",
 "history": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}],
 "mode": "agent"}
// response
{"answer": "You have spent $412 of your $800 October budget ...",
 "mode": "agent",
 "steps": [{"tool": "run_sql", "input": {"query": "SELECT ..."}, "output_preview": "[{\"sum\": 412.3}]", "is_error": false},
           {"tool": "get_forecast", "input": {"month": "2026-10"}, "output_preview": "{...}", "is_error": false}],
 "citations": [],
 "model": "nvidia/nemotron-3-super-120b-a12b:free"}
```
**One assistant for everything.** Module 4 is the single chat the user talks to. Questions about
the user's spending are answered from the database and Module 3; questions about an SGX company are
passed to Module 5 (`search_annual_reports` tool), and its page citations come back in `citations`
(same fields as Module 5's citations). So the website needs **one chat page**, not two.

The service is stateless: the frontend sends the recent `history`. `steps` lets the UI show how an
answer was computed. `mode: "baseline"` exists for the evaluation only. Status: implemented and
tested (needs a free OpenRouter key to answer). A `429` reply means the free model's limit (20 per
minute, 50 per day) was reached: the frontend should show "try again later".

### Module 5: `POST /v1/ask` and `GET /v1/documents`
```json
// POST /v1/ask request (company / fiscal_year / doc_id are optional filters)
{"question": "What was DBS's net profit in 2024?", "company": "DBS Group Holdings", "fiscal_year": 2024, "mode": "full"}
// response
{"answer": "DBS reported a net profit of ...",
 "mode": "full",
 "citations": [{"doc_id": "sgx/D05/2024", "company": "DBS Group Holdings", "fiscal_year": 2024,
                "page": 12, "quote": "Net profit rose ... to ..."}],
 "retrieved": [{"doc_id": "sgx/D05/2024", "page": 12, "chunk_type": "table", "score": 0.031}],
 "model": "nvidia/nemotron-3-super-120b-a12b:free",
 "disclaimer": "Factual information from company reports only. Not investment advice."}
// GET /v1/documents response
[{"doc_id": "sgx/D05/2024", "corpus": "sgx", "company": "DBS Group Holdings", "ticker": "D05",
  "fiscal_year": 2024, "n_pages": 180}]
```
Annual reports are public, so Module 5 does not need `X-User-Id`. Its main caller is Module 4; the
frontend only needs `/v1/documents` (optional). Status: implemented and tested on a sample report;
the real SGX and FinanceBench reports still need to be loaded.

## 5. Gateway (implemented, `services/gateway`, host port 8000)

The gateway is the only service the frontend talks to. It acts as `DEMO_USER_ID` (no login in the
demo), sets `X-User-Id` and `X-Request-ID` for the modules, and returns a `Server-Timing` header
with the time spent in each module (e.g. `extractor;dur=7.2, categoriser;dur=4.0, total;dur=12.7`).

| Public route | What it does |
|---|---|
| `GET /api/status` | which modules and the database are up |
| `GET /api/categories` | category names |
| `POST /api/entries/parse` `{"text": "..."}` | Module 1 then Module 2 -> a **draft** (nothing saved): amount, merchant, date (today if not mentioned), category, `missing_fields`, `needs_review`, plain-English `notes` |
| `POST /api/transactions` | save a confirmed draft |
| `GET /api/transactions?month=YYYY-MM&limit=` | newest first |
| `DELETE /api/transactions/{id}` | remove one |
| `GET /api/summary?month=YYYY-MM` | spent, overall budget, totals by category (with category budgets) and by day |
| `GET /api/forecast` | Module 3 on the user's transactions and this month's budget |
| `GET /api/budgets?month=` / `PUT /api/budgets` | read / set budgets (overall or per category) |
| `POST /api/chat` `{"message", "history"}` | Module 4 (which calls Modules 3 and 5 itself); 429 and 503 pass through |
| `GET /api/reports/documents` | Module 5's ingested reports |

```mermaid
sequenceDiagram
    participant UI as Frontend
    participant GW as Gateway
    participant M1 as M1 extractor
    participant M2 as M2 categoriser
    participant DB as Postgres
    UI->>GW: POST /api/transactions {"text": "chagee 4.25 yesterday"}
    GW->>M1: POST /v1/extract
    M1-->>GW: amount, merchant, date
    GW->>M2: POST /v1/categorise
    M2-->>GW: category, confidence
    GW->>DB: INSERT INTO transactions
    GW-->>UI: stored transaction
```

Keeping the database write in the gateway means Modules 1 and 2 stay stateless and can be tested
and scaled on their own.

## 6. Shared database

Schema: `db/init/002_schema.sql`. Roles: `db/init/001_roles.sh`.

| Table | Written by | Read by | DB role |
|---|---|---|---|
| `users`, `transactions`, `budgets` | gateway | gateway, Module 3 | `spendcheck_app` |
| `transactions`, `budgets` (one user's rows only) | (none) | Module 4 | `chat_agent_ro` |
| `reports.documents`, `reports.chunks` | Module 5 ingest job | Module 5 | `report_reader` |

Init scripts run only on an empty database. After a schema change, recreate the local database
with `docker compose down -v && docker compose up` (this deletes local data).

## 7. To decide at the next group meeting

1. Final category list (Module 2 owner).
2. Request and response shapes for Modules 1, 2 and 3 (section 4).
3. Who owns the gateway and the frontend.
4. Whose AWS account, and k3s on EC2 versus EKS (see `k8s/README.md` for cost).
5. GitHub repo, one branch per module, pull requests into `main`.
6. How the demo identifies the user (fixed `demo-user` or a simple login).

## 8. Checklist before a module is merged into `main`

- [ ] `docker build -f services/<name>/Dockerfile .` works from the repo root
- [ ] `/health` and `/ready` respond
- [ ] Service added to `docker-compose.yml` and `k8s/` (Deployment + Service, added to `kustomization.yaml`)
- [ ] Endpoints match section 4 (or this file is updated in the same pull request)
- [ ] `README.md` in the service folder: purpose, environment variables, how to run its evaluation
- [ ] No secrets, `.env` files or large data files committed
