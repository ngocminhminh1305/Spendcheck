# Module 5: SGX Report Reader

Answers factual questions about companies from their annual reports, with page citations, so every
answer can be checked against the source. It gives facts only, never buy or sell advice. Its main
caller is Module 4, so company questions are asked in the same chat as spending questions.

```
offline ingest:  PDF -> text + tables per page (PyMuPDF) -> page-safe chunks -> bge-small embeddings -> pgvector
question:        scope to company/year -> finance glossary expansion -> hybrid search (vector + full text, RRF)
                 -> best 6 pages, given whole -> LLM with numbered source labels -> answer + page citations
```

**Why the citations are verifiable.** The extracts given to the model are labelled [S1], [S2], ...
and the model must tag each fact with a label. Our code, not the model, maps a label to its page
(an extract never crosses a page), so a citation can only point at a page whose text the model was
actually given. The quote shown is the sentence in the cited extract sharing most words and
numbers with the answer.

`mode: "basic"` is the evaluation baseline from the proposal: the same LLM with plain dense top-k
retrieval, typing its own "[p. N]" citations.

Loaded reports: DBS (FY2025), Singapore Airlines (FY2025/26) and Sheng Siong (FY2025) annual
reports, 20 FinanceBench filings and a 5-page sample report. Sources: `data/reports/README.md`; the
PDFs are stored in Amazon S3 and the ingest job reads them from there on Kubernetes.

## API

| Endpoint | |
|---|---|
| `POST /v1/ask` | `{"question", "company", "fiscal_year", "doc_id", "mode", "top_k"}` (only `question` is required). Returns `answer`, `citations` (doc, page, quote), `retrieved`, `model` and a not-investment-advice disclaimer. |
| `GET /v1/documents` | the loaded reports: company, ticker, fiscal year, pages |
| `GET /health`, `GET /ready` | liveness; readiness (database reachable) |

Shapes: `docs/CONTRACTS.md`, section 4. Design and alternatives: `docs/PLAN_M4_M5.md`.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | | Postgres, as the `report_reader` role (owns the `reports` schema only) |
| `LLM_PROVIDER`, `LLM_MODEL`, `OPENROUTER_API_KEY` | | as for Module 4 |
| `TOP_PAGES`, `TOP_K` | 6, 8 | pages given to the LLM in full mode; chunks in basic mode |

The embedding model is downloaded when the image is built, so the service runs offline.

## Run, ingest, test, evaluate

From the repo root: `docker compose up -d` starts it with everything else (host port 8005).

```bash
docker compose run --rm report-ingest                                                # the SGX reports (download them first)
docker compose run --rm --no-deps reader-eval python -m unittest discover -s tests   # 31 unit tests
```

Downloading the PDFs and ingesting each set: `data/reports/README.md`. The evaluation (FinanceBench
and SGX questions, full versus basic) and its results: [eval/README.md](eval/README.md).
