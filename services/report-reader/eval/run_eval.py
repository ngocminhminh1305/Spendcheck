"""Module 5 evaluation: full pipeline versus basic retrieval, on FinanceBench and SGX questions.

    docker compose run --rm reader-eval python eval/run_eval.py --limit 5            # try a few
    docker compose run --rm reader-eval python eval/run_eval.py --resume             # continue another day
    docker compose run --rm reader-eval python eval/run_eval.py --judge              # grade remaining answers
    docker compose run --rm reader-eval python eval/run_eval.py --rescore            # recompute, no LLM calls
    ... --questions eval/sgx_questions.jsonl                                          # the SGX set

For every question and mode it asks POST /v1/ask (without telling the service which report: the
system has to find it, like FinanceBench's shared-vector-store setting) and records:

  doc_hit       some retrieved chunk is from the right report
  page_hit      some retrieved chunk is from a gold evidence page (retrieval recall@k)
  citations     how many cited pages are gold evidence pages (citation accuracy)
  grade         correct / incorrect / no_answer, by
                  number-match  short numeric gold answers whose numbers all appear in the answer
                  judge         an LLM compares the answer with the gold answer (--judge)
                  manual        anything you type into the grade column yourself

Free models allow 50 requests a day, so asking and judging are separate steps and both resume.
"""

import argparse
import csv
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

import httpx
from spendcheck_common.llm import LLMError, build_llm

HERE = Path(__file__).parent
FIELDS = ["id", "doc_id", "mode", "question", "gold_answer", "gold_pages", "answer", "cited", "retrieved",
          "doc_hit", "page_hit", "citations_total", "citations_correct", "grade", "grade_method",
          "server_ms", "error"]
NUMBER = re.compile(r"-?\d[\d,]*\.?\d*")
YEAR = re.compile(r"^(19|20)\d{2}$")
JUDGE_PROMPT = """\
Question: {question}
Reference answer: {gold}
Evidence from the filing: {evidence}

Answer to grade: {answer}

Grade the answer against the reference. CORRECT if it gives the same key fact or figure (rounding,
units and wording may differ). NO_ANSWER if it says the information is not available or declines.
Otherwise INCORRECT. Reply with exactly one word: CORRECT, INCORRECT or NO_ANSWER."""


def numbers(text: str) -> list[float]:
    out = []
    for raw in NUMBER.findall(text):
        cleaned = raw.replace(",", "").rstrip(".")
        if cleaned and not YEAR.match(cleaned):   # "2022" is a year, not a figure
            try:
                out.append(float(cleaned))
            except ValueError:
                pass
    return out


def number_match(gold: str, answer: str) -> bool | None:
    """True/False for short numeric gold answers; None when an LLM judge is needed."""
    gold_numbers = numbers(gold)
    if not gold_numbers or len(gold) > 40:
        return None
    found = numbers(answer)
    return all(any(abs(f - g) <= max(0.01, 0.01 * abs(g)) for f in found) for g in gold_numbers)


def score_row(row: dict) -> None:
    """Retrieval and citation metrics from the stored JSON columns (no LLM needed)."""
    gold_pages = set(json.loads(row["gold_pages"]))
    retrieved = json.loads(row["retrieved"] or "[]")
    cited = json.loads(row["cited"] or "[]")
    row["doc_hit"] = any(d == row["doc_id"] for d, _ in retrieved)
    row["page_hit"] = any(d == row["doc_id"] and p in gold_pages for d, p in retrieved)
    row["citations_total"] = len(cited)
    row["citations_correct"] = sum(1 for d, p in cited if d == row["doc_id"] and p in gold_pages)
    if row["answer"] and not row["grade"]:
        match = number_match(row["gold_answer"], row["answer"])
        if match is not None:
            row["grade"], row["grade_method"] = ("correct" if match else "incorrect"), "number-match"


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def truthy(value) -> bool:
    return value is True or value == "True"


def summarise(rows: list[dict], modes: list[str]) -> None:
    head = f"{'mode':<7}{'asked':>6}{'graded':>7}{'accuracy':>9}{'doc hit':>8}{'page hit':>9}{'cite acc':>9}{'median s':>9}{'errors':>7}"
    print("\n" + head)
    for mode in modes:
        ok = [r for r in rows if r["mode"] == mode and not r["error"]]
        graded = [r for r in ok if r["grade"]]
        cites = sum(int(r["citations_total"] or 0) for r in ok)
        right = sum(int(r["citations_correct"] or 0) for r in ok)
        times = [float(r["server_ms"]) / 1000 for r in ok if r["server_ms"]]
        pct = lambda n, d: f"{n / d:.0%}" if d else "-"
        print(f"{mode:<7}{len(ok):>6}{len(graded):>7}"
              f"{pct(sum(r['grade'] == 'correct' for r in graded), len(graded)):>9}"
              f"{pct(sum(truthy(r['doc_hit']) for r in ok), len(ok)):>8}"
              f"{pct(sum(truthy(r['page_hit']) for r in ok), len(ok)):>9}"
              f"{pct(right, cites):>9}"
              f"{statistics.median(times) if times else 0:>9.1f}"
              f"{sum(1 for r in rows if r['mode'] == mode and r['error']):>7}")
    print("accuracy = correct / graded; doc/page hit = retrieval found the right report / an evidence page;"
          "\ncite acc = cited pages that are evidence pages / all citations")


def ask_all(questions, modes, rows, args) -> bool:
    """Ask every (question, mode) not answered yet. Returns False if the rate limit stopped the run."""
    done = {(r["id"], r["mode"]) for r in rows if not r["error"]}
    rows[:] = [r for r in rows if not r["error"]]   # failed rows are retried
    base_url = os.environ.get("REPORT_READER_URL", "http://report-reader:8000")
    with httpx.Client(timeout=180.0) as client:
        for q in questions:
            for mode in modes:
                if (q["id"], mode) in done:
                    continue
                row = {k: "" for k in FIELDS} | {
                    "id": q["id"], "doc_id": q["doc_id"], "mode": mode, "question": q["question"],
                    "gold_answer": q["gold_answer"], "gold_pages": json.dumps(q["gold_pages"])}
                try:
                    resp = client.post(f"{base_url}/v1/ask", json={"question": q["question"], "mode": mode})
                    if resp.status_code == 429:
                        print("\nRate limit reached (free models: 50 requests a day). Run again later with --resume.")
                        return False
                    resp.raise_for_status()
                    body = resp.json()
                    row.update(
                        answer=body["answer"],
                        cited=json.dumps([[c["doc_id"], c["page"]] for c in body["citations"]]),
                        retrieved=json.dumps([[c["doc_id"], c["page"]] for c in body["retrieved"]]),
                        server_ms=resp.headers.get("X-Process-Time-Ms", ""))
                except httpx.HTTPError as err:
                    detail = err.response.text[:200] if isinstance(err, httpx.HTTPStatusError) else str(err)
                    row["error"] = f"{type(err).__name__}: {detail}"
                if not row["error"]:
                    score_row(row)
                rows.append(row)
                print(f"{q['id']:>18} {mode:<6} page_hit={row['page_hit']!s:<5} grade={row['grade'] or '?':<9} "
                      f"{(row['answer'] or row['error'])[:60]!r}")
                time.sleep(args.pause)
    return True


def judge_all(rows, questions_by_id, args) -> bool:
    """LLM-grade answers that number matching could not decide. Returns False on rate limit."""
    llm = build_llm()
    for row in rows:
        if row["grade"] or row["error"] or not row["answer"]:
            continue
        q = questions_by_id[row["id"]]
        prompt = JUDGE_PROMPT.format(question=q["question"], gold=q["gold_answer"],
                                     evidence=q.get("evidence", "")[:1500], answer=row["answer"])
        try:
            reply = llm.chat(system="You grade answers to questions about company reports.",
                             messages=[{"role": "user", "content": prompt}], max_tokens=2000, effort="low")
        except LLMError as err:
            if err.status == 429:
                print("\nRate limit reached. Run --judge again later.")
                return False
            print(f"judge failed for {row['id']}: {err}")
            continue
        verdict = next((w for w in ("NO_ANSWER", "INCORRECT", "CORRECT") if w in reply.text.upper()), "")
        row["grade"], row["grade_method"] = verdict.lower(), "judge"
        print(f"{row['id']:>18} {row['mode']:<6} judge -> {row['grade'] or '(unclear)'}")
        time.sleep(args.pause)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--questions", default=str(HERE / "financebench_questions.jsonl"))
    parser.add_argument("--modes", nargs="+", default=["full", "basic"], choices=["full", "basic"])
    parser.add_argument("--limit", type=int, help="only the first N questions")
    parser.add_argument("--out", help="results CSV (default: results_<questions file name>.csv)")
    parser.add_argument("--resume", action="store_true", help="keep earlier results and ask only what is missing")
    parser.add_argument("--judge", action="store_true", help="LLM-grade answers that are not graded yet")
    parser.add_argument("--rescore", action="store_true", help="recompute metrics from saved results, no LLM calls")
    parser.add_argument("--pause", type=float, default=4.0, help="seconds between requests (20/minute limit)")
    args = parser.parse_args()

    qpath = Path(args.questions)
    out = Path(args.out) if args.out else HERE / f"results_{qpath.stem}.csv"
    questions = [json.loads(line) for line in open(qpath, encoding="utf-8") if line.strip()]
    questions = questions[: args.limit] if args.limit else questions
    rows = load(out) if (args.resume or args.judge or args.rescore) else []

    finished = True
    if args.rescore:
        for row in rows:
            if not row["error"]:
                score_row(row)
    elif args.judge:
        finished = judge_all(rows, {q["id"]: q for q in questions}, args)
    else:
        finished = ask_all(questions, args.modes, rows, args)

    if rows:
        save(out, rows)
        summarise(rows, args.modes)
        print(f"\nDetailed results: {out}")
    sys.exit(0 if finished else 2)


if __name__ == "__main__":
    main()
