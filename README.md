# Spendcheck

An AI personal finance and budgeting assistant for young Singaporeans (DSA2111 Group T14).
You log spending in plain text, see whether the month is on track, and ask questions about your
money or about a company's annual report. Five AI modules run as separate Docker containers
behind a FastAPI gateway and a React website, deployed with Kubernetes (k3s) on the group's
AWS EC2 machine (Ronin).

| Module | Service | What it does | Tests |
|---|---|---|---|
| 1 Transaction entity extractor (Pham Ngoc Minh) | [services/extractor](services/extractor/README.md) | "grab to school 14.60" -> amount, merchant, date (rules, then spaCy, then GLiNER) | 161 |
| 2 Merchant categoriser (Xuanxi Yang) | [services/categoriser](services/categoriser/README.md) | merchant -> one of nine categories (verified catalogue, MiniLM fallback) | 43 |
| 3 Spending forecaster (Muhaimin Ihsan) | [services/forecaster](services/forecaster/README.md) | month-end spending forecast and budget-risk alert | 24 |
| 4 Budget chat agent (Okaggar Bo) | [services/chat-agent](services/chat-agent/README.md) | the one chat: answers spending questions with read-only SQL, uses Modules 3 and 5 as tools | 35 |
| 5 SGX report reader (Okaggar Bo) | [services/report-reader](services/report-reader/README.md) | answers questions from annual reports with page citations (hybrid search over pgvector) | 31 |
| Gateway (Okaggar Bo) | [services/gateway](services/gateway/README.md) | the website's single API; calls the modules and stores transactions and budgets | 5 |
| Website (Okaggar Bo) | `frontend` | React + Vite, served by nginx, which forwards `/api` to the gateway | build |

```
browser -> frontend (nginx) --/api--> gateway --> extractor (M1), categoriser (M2), forecaster (M3)
                                         \------> chat-agent (M4) --> forecaster (M3), report-reader (M5)
                                                  all data in Postgres + pgvector
```

* How the services talk to each other: [docs/CONTRACTS.md](docs/CONTRACTS.md)
* Design of Modules 4 and 5: [docs/PLAN_M4_M5.md](docs/PLAN_M4_M5.md)
* Changes made to Modules 1 and 3 during integration: [docs/team-changes/](docs/team-changes/README.md)
* Deploying on the group's Ronin VM with Kubernetes: [k8s/README.md](k8s/README.md)

## Run it locally

Requires Docker Desktop. Everything runs in containers; nothing is installed on the laptop.

```bash
cp .env.example .env            # set passwords and OPENROUTER_API_KEY (free, from openrouter.ai)
docker compose up -d --build
docker compose run --rm chat-eval   # create the synthetic demo-user (and eval-user)
```

Open http://localhost:3000. The M1-M5 lights at the top turn green once each module is up
(Module 1 takes about 30 s to load its models). To let Module 5 answer company questions, download
the annual reports and ingest them: [data/reports/README.md](data/reports/README.md).

The AI (Modules 4 and 5) uses OpenRouter's free models: 50 requests a day per account, 2 to 3 per
chat question. `LLM_MODEL` in `.env` is a comma-separated list; OpenRouter falls back to the next
model when one is down.

## Before a demo

The demo user's data covers the six months up to the day it was generated, so refresh it on the
morning of a demo; it also copies the database to the Ronin VM (see k8s/README.md):

```bash
bash scripts/refresh_demo.sh
```

## Tests

Each service owns its tests and its test configuration (several services use a package named
`app`), so run them per service. All of them run inside the service's own image; build the images
first (`docker compose --profile tools build`). From the repo root in Git Bash:

```bash
export MSYS_NO_PATHCONV=1   # Git Bash only: stops it rewriting the container paths below
docker run --rm -v "$PWD/services/extractor:/src:ro" -w /src spendcheck-extractor python -m pytest -q -p no:cacheprovider   # Module 1
docker run --rm -u root -v "$PWD/services/categoriser:/src:ro" -w /src spendcheck-categoriser sh -c "pip install -q pytest==9.1.1 httpx==0.28.1 && python -m pytest -q -p no:cacheprovider"   # Module 2
docker run --rm -v "$PWD/services/forecaster:/src:ro" -w /src spendcheck-forecaster sh -c "pip install -q 'pytest>=8' 'httpx>=0.27' && python -m pytest -q -p no:cacheprovider"   # Module 3
docker compose run --rm --no-deps chat-eval python -m unittest discover -s tests     # Module 4
docker compose run --rm --no-deps reader-eval python -m unittest discover -s tests   # Module 5
docker compose run --rm --no-deps -v "$PWD/services/gateway/tests:/app/tests:ro" gateway python -m unittest discover -s tests   # gateway
```

Expected: 161, 43, 24, 35, 31 and 5 tests passing (299 in total, last run 31 Oct 2026). Modules 1
to 3 also document how to run their tests outside Docker in their READMEs.

## Adding a module

Add it under `services/<module_name>/`, keeping its code, data, tests, dependencies, Dockerfile and
README together, then add it to `docker-compose.yml` and `k8s/`. Shared configuration stays at the
root.
