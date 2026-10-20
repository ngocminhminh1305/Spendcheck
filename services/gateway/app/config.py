"""Gateway settings, read from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # spendcheck_app is the role allowed to write transactions and budgets (db/init).
    database_url: str = "postgresql://spendcheck_app:change-me@localhost:5432/spendcheck"

    # The five modules, by their compose / Kubernetes service names.
    extractor_url: str = "http://extractor:8000"         # Module 1
    categoriser_url: str = "http://categoriser:8000"     # Module 2
    forecaster_url: str = "http://forecaster:8000"       # Module 3
    chat_agent_url: str = "http://chat-agent:8000"       # Module 4
    report_reader_url: str = "http://report-reader:8000" # Module 5

    # There is no login for the demo: every request acts as this user.
    demo_user_id: str = "demo-user"
    timezone: str = "Asia/Singapore"
    # Browser origins allowed to call the API directly (the Vite dev server); the production
    # site is served from the same origin through nginx and needs no CORS.
    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
