"""Evaluation baseline for Module 4 (proposal, Evaluation Plan).

"The baseline is the same LLM answering from pasted transaction history without database access."
Comparing it with agent.run_agent on the same questions shows whether letting the agent run
database queries improves accuracy. Same model, same effort; only the method differs.
"""

import csv
import io
from datetime import date

from psycopg_pool import ConnectionPool
from spendcheck_common.llm import LLM

from . import db
from .config import Settings
from .prompts import date_context
from .schemas import ChatRequest, ChatResponse

BASELINE_SYSTEM = """\
You are Spendcheck, a budgeting assistant for young people in Singapore. Answer the user's
question using only the transaction history and budgets provided in the message. Amounts are in
SGD. Weeks run Monday to Sunday; "last week" is the previous full Monday-to-Sunday week.
Answer in two to four short sentences with the key numbers rounded to cents.
"""


def _history_csv(pool: ConnectionPool, user_id: str, timeout_ms: int) -> tuple[str, str]:
    """The user's full transaction history and budgets as two CSV strings."""
    with db.user_scoped_readonly(pool, user_id, timeout_ms) as conn:
        txns = conn.execute(
            "SELECT txn_date, amount, merchant, category FROM transactions ORDER BY txn_date, txn_id"
        ).fetchall()
        budgets = conn.execute(
            "SELECT month, COALESCE(category, 'ALL') AS category, amount FROM budgets ORDER BY month, category"
        ).fetchall()

    def to_csv(header: list[str], rows) -> str:
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(header)
        writer.writerows(rows)
        return out.getvalue()

    return (to_csv(["date", "amount", "merchant", "category"], txns),
            to_csv(["month", "category", "budget"], budgets))


def answer_from_pasted_history(
    request: ChatRequest,
    user_id: str,
    *,
    llm: LLM,
    pool: ConnectionPool,
    settings: Settings,
    today: date,
) -> ChatResponse:
    """One LLM call with the whole history pasted in as CSV, and no tools."""
    # Generous timeout: this reads every row, unlike the agent's targeted queries.
    txn_csv, budget_csv = _history_csv(pool, user_id, timeout_ms=settings.sql_timeout_ms * 5)
    prompt = (
        f"{date_context(today, settings.timezone)}\n\n"
        f"<transactions>\n{txn_csv}</transactions>\n\n"
        f"<budgets>\n{budget_csv}</budgets>\n\n"
        f"Question: {request.message}"
    )
    messages = [{"role": t.role, "content": t.content} for t in request.history]
    messages.append({"role": "user", "content": prompt})

    reply = llm.chat(system=BASELINE_SYSTEM, messages=messages,
                     max_tokens=settings.llm_max_tokens, effort=settings.llm_effort)
    answer = "Sorry, I can't help with that." if reply.stop == "refusal" else reply.text.strip()
    return ChatResponse(answer=answer, mode="baseline", steps=[], model=llm.model)
