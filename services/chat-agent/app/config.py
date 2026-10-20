"""Chat agent settings, read from environment variables so one image runs everywhere.

LLM settings (LLM_PROVIDER, LLM_MODEL, AWS_REGION, ...) are read by spendcheck_common.llm.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Connects as chat_agent_ro: read-only, and row-level security limits it to one user's rows.
    database_url: str = "postgresql://chat_agent_ro:change-me@localhost:5432/spendcheck"

    # Other services this agent calls, by their in-cluster / compose names.
    forecaster_url: str = "http://forecaster:8000"         # Module 3
    report_reader_url: str = "http://report-reader:8000"   # Module 5

    agent_max_steps: int = 6      # max LLM -> tool -> LLM round trips for one question
    sql_row_limit: int = 200      # rows returned to the LLM per query
    sql_timeout_ms: int = 3000    # Postgres statement_timeout for agent-written SQL
    tool_output_chars: int = 20000  # longest tool result sent back to the LLM
    llm_effort: str = "medium"    # Claude effort level: low | medium | high
    llm_max_tokens: int = 16000

    timezone: str = "Asia/Singapore"   # "today" / "last week" are resolved in this zone
    # When true, the X-Eval-Today header can set "today", so evaluation questions such as
    # "last week" always mean the same dates. Leave false in production.
    eval_mode: bool = False
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
