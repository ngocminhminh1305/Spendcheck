# Module 5 evaluation

From the proposal: run FinanceBench questions and compare with the FinanceBench paper; write ~30
questions on SGX annual reports; measure citation accuracy; and compare the full pipeline with the
same LLM using basic retrieval.

## Data

| Set | Questions | Reports | Where |
|---|---|---|---|
| FinanceBench subset | 74 (of the 150 open-source questions) | the 20 filings covering the most questions (10-K, 10-Q, 8-K, earnings releases; 15 US companies), 35 MB | PDFs + `manifest.csv` in `data/reports/financebench/`; questions in `financebench_questions.jsonl` |
| SGX | 3, answers checked by hand against the PDFs (20 Oct 2026) | DBS FY2025, Singapore Airlines FY2025/26, Sheng Siong FY2025 annual reports | `data/reports/sgx/` (sources in `data/reports/README.md`); `sgx_questions.jsonl` |
| Sample | none (used by tests and demos) | generated 5-page report | `make_sample_report.py` |

FinanceBench's `evidence_page_num` is **0-based** (checked: 90 of 91 evidence quotes are on that
page counting from 0), so `financebench_questions.jsonl` stores `gold_pages` as 1-based pages,
matching our citations. Each question keeps FinanceBench's `question_type`
(domain-relevant / novel-generated / metrics-generated) for per-type results.

## Run it (from the repo root, everything inside Docker)

```bash
docker compose run --rm reader-eval python -m ingest.run --manifest /data/reports/financebench/manifest.csv
docker compose run --rm reader-eval python eval/run_eval.py --limit 5     # try a few first
docker compose run --rm reader-eval python eval/run_eval.py --resume      # each day until done
docker compose run --rm reader-eval python eval/run_eval.py --judge       # grade what number-matching could not
docker compose run --rm reader-eval python eval/run_eval.py --rescore     # recompute metrics, no LLM calls
```

Add `--questions eval/sgx_questions.jsonl` for the SGX set. Results: `eval/results_<set>.csv`.
(In Git Bash, prefix commands that contain `/data/...` paths with `MSYS_NO_PATHCONV=1`.)

## Metrics

| Metric | Meaning |
|---|---|
| doc hit | retrieval found at least one chunk from the right filing (the service is *not* told which filing) |
| page hit | retrieval found a chunk from a gold evidence page: retrieval recall@k |
| citation accuracy | cited pages that are gold evidence pages / all citations |
| accuracy | correct answers / graded answers |
| latency | median server time per question |

Grading: short numeric gold answers are graded automatically when every gold number appears in the
answer (within 1%, years ignored); the rest are graded by an LLM judge (`--judge`) that sees the
question, gold answer, FinanceBench evidence and our answer. Spot-check about 20% of judge grades
by hand and report the agreement; you can overwrite any `grade` in the CSV yourself (set
`grade_method` to `manual`).

## Development check (16 Oct 2026, first 5 questions, all 3M, free Nemotron model)

The first version answered 0 of 5: it found the right filing every time but often not the right
page, and it refused to calculate. Two retrieval changes and one prompt change fixed most of it:

| Change | Why |
|---|---|
| finance glossary query expansion (`app/glossary.py`) | "capital-intensive", "quick ratio" and "dragged down growth" are not the words statements use ("purchases of property, plant and equipment", "total current assets", "organic sales") |
| whole pages instead of fragments | the 10-Q cover page's list of registered notes was split across chunks and the useful chunk was missed |
| allow calculations, with the working shown | FinanceBench expects ratios and judgements worked out from the statements |

After: about 4 to 4.5 of 5 correct (the quick ratio came out 0.85 versus the gold 0.96, with the
same conclusion). Evidence page found for 3 of 5, up from 2. `dev_check_5q_after_fixes.csv` keeps
those answers. Note that one "wrong" citation (pp. 32-33 for the segment question) does show the
gold figure; the fact simply appears on more than one page, so also report a hand-checked citation
accuracy on a sample.

## Held-out run (27 Oct 2026, 8 questions, nvidia/nemotron-3-ultra-550b-a55b:free)

The free models allow 50 requests a day, and all 74 questions in both modes plus judge calls need
about 250, so the full set was not run. Instead, `financebench_run_27oct.jsonl` holds 8 held-out
questions, one from each of the 8 filings that follow the 3M 10-K in alphabetical order (3M 10-Q
to Best Buy 10-K): for each filing, its first question that was not in the 5-question
development check.

```bash
docker compose run --rm reader-eval python eval/run_eval.py --questions eval/financebench_run_27oct.jsonl --pause 8
```

| Mode | Correct | Evidence page retrieved | Citations on evidence pages | Median |
|---|---|---|---|---|
| full | 7/8 | 6/8 | 4/10 | 13.6 s |
| basic | 3/8 | 2/8 | 2/22 | 7.7 s |

Results are in `results_financebench_run_27oct.csv`. Short numeric answers were graded by number
matching; the other 14 rows were graded by hand against `gold_answer` (`grade_method` = `manual`).

The FinanceBench paper reports results for several set-ups, including a vector store shared
across all filings, which is closest to our `basic` mode. Our `full` mode adds company/year
scoping, hybrid search and source-label citations.
