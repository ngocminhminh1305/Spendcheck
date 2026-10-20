"""Tools the chat agent may call, and one dispatcher that runs them.

To add a tool: write its TOOL_DEFINITION and function in a new module, list the definition in
TOOL_DEFINITIONS, and add a branch to execute_tool.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx
import psycopg
from psycopg_pool import ConnectionPool

from .. import db
from ..config import Settings
from . import forecast_tool, reports_tool, sql_tool

log = logging.getLogger(__name__)

# Sent to Claude in the `tools` field. Keep the order fixed: a changing tool list breaks prompt caching.
TOOL_DEFINITIONS = [
    sql_tool.TOOL_DEFINITION,
    forecast_tool.TOOL_DEFINITION,
    reports_tool.TOOL_DEFINITION,
]


@dataclass
class ToolContext:
    """Everything a tool needs about the current request."""

    user_id: str
    request_id: str | None
    pool: ConnectionPool
    settings: Settings
    today: date    # "today" for this request (the evaluation can fix it)


@dataclass
class ToolResult:
    content: str                          # text sent back to the LLM in the tool_result block
    is_error: bool = False
    citations: list[dict[str, Any]] = field(default_factory=list)   # report pages, for the UI


def execute_tool(name: str, tool_input: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Run one tool call. Expected failures become is_error results so the LLM can recover."""
    s = ctx.settings
    try:
        if name == "run_sql":
            with db.user_scoped_readonly(ctx.pool, ctx.user_id, s.sql_timeout_ms) as conn:
                return ToolResult(sql_tool.run_sql(conn, tool_input["query"], s.sql_row_limit))

        if name == "get_forecast":
            # Module 3 is stateless: send it this user's transactions and budget.
            with db.user_scoped_readonly(ctx.pool, ctx.user_id, s.sql_timeout_ms * 5) as conn:
                transactions, budget = forecast_tool.load_inputs(conn, ctx.today)
            data = forecast_tool.get_forecast(s.forecaster_url, transactions, ctx.today, budget, ctx.request_id)
            return ToolResult(json.dumps(data))

        if name == "search_annual_reports":
            data = reports_tool.search_annual_reports(s.report_reader_url, tool_input["question"], ctx.request_id)
            citations = data.get("citations", [])
            compact = {
                "answer": data.get("answer", ""),
                "citations": [{"company": c.get("company"), "year": c.get("fiscal_year"), "page": c.get("page"),
                               "quote": c.get("quote")} for c in citations],
            }
            return ToolResult(json.dumps(compact), citations=citations)

        return ToolResult(f"Unknown tool {name!r}.", is_error=True)

    except sql_tool.UnsafeSQLError as err:
        return ToolResult(f"Query rejected: {err}", is_error=True)
    except psycopg.Error as err:
        # e.g. a misspelt column or a timeout: tell the LLM so it can correct the query
        return ToolResult(f"Database error: {str(err).strip()}", is_error=True)
    except httpx.HTTPError as err:
        log.warning("tool %s failed: %s", name, err)
        return ToolResult(f"The {name} service is unavailable right now ({type(err).__name__}).", is_error=True)
