"""Report reader settings, read from environment variables.

LLM settings (LLM_PROVIDER, LLM_MODEL, AWS_REGION, ...) are read by spendcheck_common.llm.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Connects as report_reader, which owns the reports schema and nothing else.
    database_url: str = "postgresql://report_reader:change-me@localhost:5432/spendcheck"

    # Where the annual-report PDFs live (used by the ingest job).
    reports_bucket: str = "spendcheck-reports"
    reports_prefix: str = "raw/"

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384                 # must match vector(384) in db/init/002_schema.sql
    embedding_cache_dir: str | None = None   # /models inside the image

    top_k: int = 8                 # basic mode: chunks given to the LLM per question
    top_pages: int = 6             # full mode: whole pages given to the LLM per question
    candidate_k: int = 40          # full mode: chunks fetched from each retriever before fusion
    llm_effort: str = "medium"
    llm_max_tokens: int = 16000
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
