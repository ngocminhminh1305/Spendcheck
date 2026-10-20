"""run_sql tool: lets the agent query the user's transactions with SQL it writes itself.

validate_sql is the first of four safety layers. The other three are enforced by Postgres
(see db.py): a read-only login, a READ ONLY transaction, and row-level security.
"""

import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

ALLOWED_TABLES = {"transactions", "budgets", "categories"}

# Functions an LLM-written query must never call. set_config could switch the user that
# row-level security filters on; the *_to_xml functions run SQL hidden inside a string, which
# would skip the table check; pg_* are server internals (pg_sleep, pg_read_file, ...).
_FORBIDDEN_FUNCTION = re.compile(
    r"^(set_config|current_setting|pg_\w+|dblink\w*|lo_\w+|query_to_xml\w*|"
    r"(table|cursor|schema|database)_to_xml\w*)$"
)
_WRITE_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop,
                exp.Alter, exp.Command, exp.Copy)

TOOL_DEFINITION = {
    "name": "run_sql",
    "description": (
        "Run one read-only PostgreSQL SELECT query on the user's spending data and return the rows "
        "as JSON. Tables: transactions, budgets, categories (see system prompt for columns). "
        "Rows are already limited to the current user. Use aggregates (SUM, COUNT, GROUP BY) "
        "instead of fetching many raw rows."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "A single SELECT statement (CTEs allowed)."},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}


class UnsafeSQLError(ValueError):
    """The query is not a single safe SELECT. The message is sent back to the LLM so it can retry."""


def validate_sql(query: str, row_limit: int) -> str:
    """Return a safe, LIMIT-ed version of `query`, or raise UnsafeSQLError."""
    try:
        statements = [s for s in sqlglot.parse(query, read="postgres") if s is not None]
    except SqlglotError as err:
        raise UnsafeSQLError(f"Could not parse the SQL: {err}") from err

    if len(statements) != 1:
        raise UnsafeSQLError("Send exactly one SQL statement.")
    stmt = statements[0]

    # 1. Only queries that read: SELECT, or UNION/INTERSECT/EXCEPT of SELECTs.
    if not isinstance(stmt, (exp.Select, exp.SetOperation)):
        raise UnsafeSQLError("Only SELECT queries are allowed.")
    if any(True for _ in stmt.find_all(*_WRITE_NODES)):
        raise UnsafeSQLError("Only SELECT queries are allowed (no INSERT, UPDATE, DELETE or DDL).")
    if any(s.args.get("into") for s in stmt.find_all(exp.Select)):
        raise UnsafeSQLError("SELECT ... INTO is not allowed.")

    # 2. Only the user's spending tables. Names defined by WITH clauses are fine.
    cte_names = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}
    for table in stmt.find_all(exp.Table):
        if isinstance(table.this, exp.Func):   # FROM generate_series(...): checked as a function below
            continue
        name = table.name.lower()
        schema = (table.db or "").lower()
        if schema not in ("", "public") or (name not in ALLOWED_TABLES and name not in cte_names):
            shown = f"{schema}.{name}" if schema else name
            raise UnsafeSQLError(f"Table {shown!r} is not available. Use: {', '.join(sorted(ALLOWED_TABLES))}.")

    # 3. No functions that could escape the sandbox.
    for func in stmt.find_all(exp.Func):
        name = (func.name if isinstance(func, exp.Anonymous) else func.sql_name()).lower()
        if _FORBIDDEN_FUNCTION.match(name):
            raise UnsafeSQLError(f"Function {name}() is not allowed.")

    # 4. Cap the result size if the query did not.
    if not stmt.args.get("limit"):
        stmt = stmt.limit(row_limit)
    return stmt.sql(dialect="postgres")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def run_sql(conn: psycopg.Connection, query: str, row_limit: int) -> str:
    """Validate and execute `query` on a user-scoped read-only connection; return rows as JSON text.

    Raises UnsafeSQLError for rejected SQL and psycopg.Error for database errors (for example a
    misspelt column); the agent turns both into an error tool_result so the LLM can fix its query.
    """
    safe_sql = validate_sql(query, row_limit)
    with conn.cursor() as cur:
        cur.execute(safe_sql)
        columns = [col.name for col in cur.description] if cur.description else []
        rows = cur.fetchmany(row_limit)
    result = {
        "columns": columns,
        "rows": [[_jsonable(v) for v in row] for row in rows],
        "row_count": len(rows),
        "executed_sql": safe_sql,
    }
    return json.dumps(result)
