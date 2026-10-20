"""Module 4 evaluation: the agent versus the pasted-history baseline, on questions with known answers.

    docker compose run --rm chat-eval python eval/run_eval.py --limit 5        # try a few first
    docker compose run --rm chat-eval python eval/run_eval.py                  # everything
    docker compose run --rm chat-eval python eval/run_eval.py --resume         # continue another day

Needs the stack running (chat-agent with EVAL_MODE=true, the default in docker-compose.yml),
eval-user seeded by eval/seed_synthetic_user.py, and a working LLM key.

Free OpenRouter models allow 50 requests a day; one agent question uses 2 or 3, a baseline
question 1. When the limit is hit the run stops, keeps what it has, and --resume skips every
question already answered. Gold answers come from each question's gold_sql run on eval-user's
data, so they always match the database. Results: eval/results.csv, plus a summary table.
"""

import argparse
import csv
import json
import os
import re
import statistics
import sys
import time
from decimal import Decimal
from pathlib import Path

import httpx

from app import db
from app.config import Settings

EVAL_USER = "eval-user"
HERE = Path(__file__).parent
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")
FIELDS = ["id", "mode", "question", "gold", "answer", "correct", "server_ms", "wall_ms", "tool_calls", "error"]


def gold_answer(pool, sql: str):
    """Run gold_sql as eval-user (row-level security applies, exactly as for the agent)."""
    with db.user_scoped_readonly(pool, EVAL_USER, timeout_ms=10000) as conn:
        row = conn.execute(sql).fetchone()
    value = row[0] if row else None
    return float(value) if isinstance(value, (Decimal, int, float)) else value


NUMBER_WORDS = {
    "once": 1, "twice": 2, "thrice": 3, "zero": 0, "none": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
WORD = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", re.IGNORECASE)


def numbers_in(text: str) -> list[float]:
    """Every number in an answer, including small counts written as words ("twice", "three")."""
    text = ISO_DATE.sub(" ", text)   # so "2026-10-05" is not read as three numbers
    found = [float(n.replace(",", "")) for n in NUMBER.findall(text)]
    return found + [float(NUMBER_WORDS[w.lower()]) for w in WORD.findall(text)]


def is_correct(answer: str, gold, answer_type: str) -> bool:
    """number: some number in the answer is within 1 cent (or 0.5%) of gold; text: gold appears in it.

    Numbers are compared without their sign: "you overspent by $445.85" or "it fell by $0.98" are
    correct for gold answers of -445.85 and -0.98, since people state direction in words.
    """
    if gold is None:
        return False
    if answer_type == "number":
        tolerance = max(0.01, 0.005 * abs(gold))
        return any(abs(abs(n) - abs(gold)) <= tolerance for n in numbers_in(answer))
    return str(gold).lower() in answer.lower()


def p95(values: list[float]) -> float:
    return statistics.quantiles(values, n=20)[18] if len(values) >= 2 else (values[0] if values else 0.0)


def load_previous(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:   # CSV gives strings back
        r["correct"] = r["correct"] == "True"
        r["server_ms"] = float(r["server_ms"]) if r["server_ms"] else None
    return rows


def summarise(results: list[dict], modes: list[str]) -> None:
    print(f"\n{'mode':<9}{'answered':>9}{'accuracy':>10}{'median ms':>11}{'p95 ms':>9}{'errors':>8}")
    for mode in modes:
        rows = [r for r in results if r["mode"] == mode]
        answered = [r for r in rows if not r["error"]]
        times = [r["server_ms"] for r in answered if r["server_ms"] is not None]
        accuracy = sum(r["correct"] for r in answered) / len(answered) if answered else 0.0
        print(f"{mode:<9}{len(answered):>9}{accuracy:>10.1%}{statistics.median(times) if times else 0:>11.0f}"
              f"{p95(times):>9.0f}{len(rows) - len(answered):>8}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--questions", default=str(HERE / "questions.jsonl"))
    parser.add_argument("--modes", nargs="+", default=["agent", "baseline"], choices=["agent", "baseline"])
    parser.add_argument("--limit", type=int, help="only the first N questions")
    parser.add_argument("--out", default=str(HERE / "results.csv"))
    parser.add_argument("--resume", action="store_true", help="skip questions already answered in --out")
    parser.add_argument("--pause", type=float, default=8.0,
                        help="seconds between questions (free models allow 20 requests/minute)")
    parser.add_argument("--rescore", action="store_true",
                        help="re-mark the saved answers in --out with the current scoring; no LLM calls")
    args = parser.parse_args()

    out = Path(args.out)
    questions = [json.loads(line) for line in open(args.questions, encoding="utf-8") if line.strip()]
    questions = questions[: args.limit] if args.limit else questions

    if args.rescore:
        types = {q["id"]: q["answer_type"] for q in questions}
        rows = load_previous(out)
        for r in rows:
            gold = float(r["gold"]) if types.get(r["id"]) == "number" and r["gold"] else r["gold"]
            r["correct"] = not r["error"] and is_correct(r["answer"], gold, types.get(r["id"], "text"))
        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        summarise(rows, args.modes)
        return
    previous = load_previous(out) if args.resume else []
    done = {(r["id"], r["mode"]) for r in previous if not r["error"]}
    results = [r for r in previous if not r["error"]]   # failed rows are retried

    base_url = os.environ.get("CHAT_AGENT_URL", "http://chat-agent:8000")
    pool = db.create_pool(Settings().database_url)
    stopped_early = False

    with httpx.Client(timeout=180.0) as client:
        for q in questions:
            todo = [m for m in args.modes if (q["id"], m) not in done]
            if not todo:
                continue
            gold = gold_answer(pool, q["gold_sql"])
            for mode in todo:
                started = time.perf_counter()
                row = {"id": q["id"], "mode": mode, "question": q["question"], "gold": gold, "answer": "",
                       "correct": False, "server_ms": None, "wall_ms": None, "tool_calls": 0, "error": ""}
                try:
                    resp = client.post(
                        f"{base_url}/v1/chat",
                        json={"message": q["question"], "mode": mode},
                        headers={"X-User-Id": EVAL_USER, "X-Eval-Today": q["asked_on"]},
                    )
                    if resp.status_code == 429:
                        stopped_early = True
                        print("\nRate limit reached (free models: 50 requests a day). Run again later with --resume.")
                        break
                    resp.raise_for_status()
                    body = resp.json()
                    row.update(answer=body["answer"], tool_calls=len(body.get("steps", [])),
                               correct=is_correct(body["answer"], gold, q["answer_type"]),
                               server_ms=float(resp.headers.get("X-Process-Time-Ms", 0)))
                except httpx.HTTPError as err:
                    detail = err.response.text[:200] if isinstance(err, httpx.HTTPStatusError) else str(err)
                    row["error"] = f"{type(err).__name__}: {detail}"
                row["wall_ms"] = round((time.perf_counter() - started) * 1000, 1)
                results.append(row)
                mark = "ERR" if row["error"] else ("OK " if row["correct"] else "X  ")
                print(f"{q['id']:>5} {mode:<8} {mark} gold={gold!r}  {(row['answer'] or row['error'])[:70]!r}")
                time.sleep(args.pause)
            if stopped_early:
                break

    if results:
        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(results)
        summarise(results, args.modes)
        print(f"\nDetailed results: {out}")
    pool.close()
    sys.exit(2 if stopped_early else 0)


if __name__ == "__main__":
    main()
