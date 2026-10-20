# Module 4 evaluation

From the proposal: about 50 questions with known answers about a synthetic user's transactions.
Answers are checked against results computed directly from the database. The baseline is the
same LLM answering from pasted transaction history without database access.

## Run it (from the repo root, everything inside Docker)

```bash
docker compose up -d                                                   # Postgres + services
docker compose run --rm chat-eval                                      # seed eval-user and demo-user
docker compose run --rm chat-eval python eval/run_eval.py --limit 5    # try a few first (costs LLM tokens)
docker compose run --rm chat-eval python eval/run_eval.py              # all questions, both modes
```

Results go to `eval/results.csv`; the script prints accuracy, median and p95 latency per mode.
`OPENROUTER_API_KEY` in `.env` must be set (see `.env.example`).

**Free-model limits:** 20 requests a minute and 50 a day. An agent question uses 2 or 3 requests and
a baseline question 1, so about 15 to 20 questions fit in a day. The script waits 8 seconds between
questions, stops cleanly when the daily limit is hit, and on the next day
`python eval/run_eval.py --resume` carries on where it stopped. The full run (~50 questions, both
modes) takes about five days, so start early. Use the same model for both modes.

## Files

| File | Purpose |
|---|---|
| `seed_synthetic_user.py` | `eval-user`: fixed-seed Singapore-style spending from 1 Apr to 13 Oct 2026 (628 transactions), monthly budgets. `demo-user`: the same style for the last 6 months, for the live demo. Re-running replaces both. |
| `questions.jsonl` | One question per line: `id`, `question`, `gold_sql`, `answer_type` (`number` or `text`), `asked_on`. **5 written; extend to ~50.** |
| `run_eval.py` | Computes each gold answer by running `gold_sql` as `eval-user`, asks `/v1/chat` in `agent` and `baseline` mode, scores, records latency. |

## Writing the remaining questions

Cover a spread so the report can break accuracy down by type:

* totals over a period ("this month", "last week", "in August")
* counts ("how many times did I take Grab in September?")
* max / min / average ("biggest purchase", "average Kopitiam meal")
* per-category comparisons ("did I spend more on food or transport last month?")
* budgets ("how much of my October food budget is left?")
* trends ("which month did I spend the most?")

`gold_sql` never filters by user: it runs with row-level security as `eval-user`, like the agent.
All questions use `asked_on: 2026-10-13`, the last day of eval-user's data, which the evaluation
sends as "today" (`X-Eval-Today`, honoured only when `EVAL_MODE=true`).

## Scoring

* `number`: correct if any number in the answer is within 1 cent (or 0.5% for large sums) of the
  gold value. Small counts written as words ("twice", "three") count too, and ISO dates are ignored
  so "2026-10-05" is not read as numbers. This is lenient when an answer quotes many numbers, so
  spot-check a sample by hand and report it.
* After changing the scoring, `python eval/run_eval.py --rescore` re-marks the saved answers in
  `results.csv` without any new LLM requests.

## First run (15 Oct 2026, 5 questions, nvidia/nemotron-3-super-120b-a12b:free)

| Mode | Correct | Median | p95 |
|---|---|---|---|
| agent | 5/5 | 11.6 s | 46.0 s |
| baseline | 4/5 | 56.1 s | 201.4 s |

The baseline's miss (q01) took "last week" as Mon 6 to Sun 12 Oct, but 6 Oct 2026 is a Tuesday,
so it summed the wrong days ($71.70 instead of $62.40). The agent resolves the dates in SQL instead.
* Signs are ignored: for gold answers like -445.85 (overspent) or -0.98 (a fall), "overspent by
  $445.85" counts as correct, because people give direction in words. Check sign-sensitive rows
  (q42, q45 to q50) by hand when reporting.
* `text`: correct if the gold value (for example a category name) appears in the answer.

## Question set

`questions.jsonl` has 50 questions (drafted with ChatGPT from `docs/QUESTION_PROMPTS.md`, then
checked by running every `gold_sql`: all run, all return an answer, and no "which category/merchant"
question has a tie). Mix: totals, counts, max/min/average, category and merchant comparisons,
budgets, and month-to-month changes.
