# Module 4: Budget Chat Agent

The one chat assistant in Spendcheck. It answers questions about the user's own spending ("How much
did I spend on food last week?", "Can I afford a S$300 concert ticket?") and, by handing them to
Module 5, questions about a company's annual report, in the same conversation.

```
question -> LLM agent loop (up to 6 steps) -> tools -> plain-English answer + the steps it took
              run_sql                 one read-only SELECT on the user's transactions and budgets
              get_forecast            Module 3: month-end forecast and budget-risk alert
              search_annual_reports   Module 5: answer with page citations
```

**Grounded numbers.** The model does not add up amounts itself: it writes SQL, and the database
does the arithmetic. Dates such as "last week" are resolved in SQL from today's date in Singapore.

**SQL safety, four layers.** `app/tools/sql_tool.py` uses sqlglot to allow exactly one SELECT on
`transactions`, `budgets` and `categories`; the `chat_agent_ro` login has SELECT grants only; each
query runs in a READ ONLY transaction with a 3-second timeout; and Postgres row-level security
hides every row that is not the current user's (set from the `X-User-Id` header). The last layer
is enforced by the database, so it holds even if the others fail.

**Persona.** The website can send `{"name", "tone"}`; it changes the wording only, never the
numbers (`app/prompts.py`). The evaluation sends no persona.

## API

| Endpoint | |
|---|---|
| `POST /v1/chat` | `{"message", "history", "mode", "persona"}`, header `X-User-Id`. Returns `answer`, `steps`, `citations`, `model`. `mode: "baseline"` (no tools, history pasted as CSV) is for the evaluation only. A 429 means the free model's limit was reached. |
| `GET /health`, `GET /ready` | liveness; readiness (database reachable) |

Shapes: `docs/CONTRACTS.md`, section 4. Design: `docs/PLAN_M4_M5.md`.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | | Postgres, as the read-only `chat_agent_ro` role |
| `FORECASTER_URL`, `REPORT_READER_URL` | `http://forecaster:8000`, `http://report-reader:8000` | Modules 3 and 5 |
| `LLM_PROVIDER` | `openrouter` | or `anthropic` / `bedrock` (`libs/common/spendcheck_common/llm.py`) |
| `LLM_MODEL` | three free OpenRouter models | comma-separated: OpenRouter falls back to the next one when a model is down |
| `OPENROUTER_API_KEY` | | free key from openrouter.ai (20 requests a minute, 50 a day) |
| `AGENT_MAX_STEPS`, `SQL_TIMEOUT_MS` | 6, 3000 | agent step limit; Postgres timeout for agent-written SQL |
| `EVAL_MODE` | false | when true, the `X-Eval-Today` header can fix "today" (evaluation only) |

## Run, test, evaluate

From the repo root: `docker compose up -d` starts it with everything else (host port 8004).

```bash
docker compose run --rm chat-eval                                                  # seed demo-user and eval-user
docker compose run --rm --no-deps chat-eval python -m unittest discover -s tests   # 35 unit tests
```

The evaluation (50 questions with gold SQL, agent versus the same LLM without database access) and
its results are described in [eval/README.md](eval/README.md).
