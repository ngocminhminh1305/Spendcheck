# Module 4 evaluation

From the proposal: about 50 questions with known answers about a synthetic user's transactions.
Answers are checked against results computed directly from the database. The baseline is the
same LLM answering from pasted transaction history without database access.

## Run it (from the repo root, everything inside Docker)

```bash
docker compose up -d                                                   # Postgres + services
docker compose run --rm chat-eval                                      # seed eval-user and demo-user
docker compose run --rm chat-eval python eval/run_eval.py --limit 5    # try a few first (costs LLM requests)
docker compose run --rm chat-eval python eval/run_eval.py              # all questions, both modes
```

Results go to `eval/results.csv` (`--out` to change it); the script prints accuracy, median and
p95 latency per mode. `OPENROUTER_API_KEY` in `.env` must be set (see `.env.example`).

**Free-model limits:** 20 requests a minute and 50 a day. An agent question uses 2 or 3 requests and
a baseline question 1, so about 15 to 20 questions fit in a day. The script waits 8 seconds between
questions, stops cleanly when the daily limit is hit, and `python eval/run_eval.py --resume` carries
on where it stopped. All 50 questions in both modes would take about five days of free requests.

## Files

| File | Purpose |
|---|---|
| `seed_synthetic_user.py` | `eval-user`: fixed-seed Singapore-style spending from 1 Apr to 13 Oct 2026 (628 transactions), monthly budgets. `demo-user`: the same style for the six months up to the day it runs, for the live demo. Re-running replaces both. |
| `questions.jsonl` | The 50 questions, one per line: `id`, `question`, `gold_sql`, `answer_type` (`number` or `text`), `asked_on`. |
| `questions_run_27oct.jsonl` | q06 to q15 from `questions.jsonl`, the subset used in run 2. |
| `run_eval.py` | Computes each gold answer by running `gold_sql` as `eval-user`, asks `/v1/chat` in `agent` and `baseline` mode, scores, records latency. |
| `results.csv`, `results_run_27oct.csv` | Answers, scores and latencies of runs 1 and 2. |

## Question set

`questions.jsonl` has 50 questions (drafted with ChatGPT from `docs/QUESTION_PROMPTS.md`, then
checked by running every `gold_sql`: all run, all return an answer, and no "which category/merchant"
question has a tie). Mix: totals over a period, counts, max/min/average, category and merchant
comparisons, budgets, and month-to-month changes.

`gold_sql` never filters by user: it runs with row-level security as `eval-user`, like the agent.
All questions use `asked_on: 2026-10-13`, the last day of eval-user's data, which the evaluation
sends as "today" (`X-Eval-Today`, honoured only when `EVAL_MODE=true`).

## Scoring

* `number`: correct if any number in the answer is within 1 cent (or 0.5% for large sums) of the
  gold value. Small counts written as words ("twice", "three") count too, and ISO dates are ignored
  so "2026-10-05" is not read as numbers. This is lenient when an answer quotes many numbers, so
  the answers were also checked by hand.
* Signs are ignored: for gold answers like -445.85 (overspent) or -0.98 (a fall), "overspent by
  $445.85" counts as correct, because people give direction in words. Check sign-sensitive rows
  (q42, q45 to q50) by hand when reporting.
* `text`: correct if the gold value (for example a category name) appears in the answer.
* After changing the scoring, `python eval/run_eval.py --rescore` re-marks the saved answers
  without any new LLM requests.

## Results

Because of the free-model limit, 15 of the 50 questions were run, in two runs.

| Run | Questions | Model | Mode | Correct | Median |
|---|---|---|---|---|---|
| 1 (15 Oct 2026) | q01 to q05 | nvidia/nemotron-3-super-120b-a12b:free | agent | 5/5 | 11.6 s |
| | | | baseline | 4/5 | 56.1 s |
| 2 (27 Oct 2026) | q06 to q15 | nvidia/nemotron-3-ultra-550b-a55b:free | agent | 10/10 | 6.4 s |
| | | | baseline | 7/10 | 12.4 s |
| Total | 15 | | agent | 15/15 | |
| | | | baseline | 11/15 | |

Run 2 was answered by Nemotron 3 Ultra, the next model in the `LLM_MODEL` fallback list, because
Nemotron 3 Super was unavailable on OpenRouter that day; both modes used the same model in each run.
Reproduce run 2 with:

```bash
docker compose run --rm chat-eval python eval/run_eval.py --questions eval/questions_run_27oct.jsonl --out eval/results_run_27oct.csv
```

The baseline's misses:

* q01 took "last week" as Mon 6 to Sun 12 Oct, but 6 Oct 2026 is a Tuesday, so it summed the
  wrong days ($71.70 instead of $62.40). The agent resolves the dates in SQL instead.
* q12 and q15 added up the pasted history and came out too low ($229.80 instead of $236.90, and
  $106.95 instead of $129.30); q14 returned an empty answer.
