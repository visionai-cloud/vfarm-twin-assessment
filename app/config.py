"""Runtime configuration, loaded from environment / .env."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"  # "production" tightens startup checks
    log_level: str = "INFO"

    database_url: str = "sqlite:///./vfarm.db"
    webhook_token: str = "dev-secret-change-me"
    sheet_csv_url: str = "./sample_data/builder_updates.csv"
    sheet_poll_seconds: int = 300

    # Cap on events pulled into memory for the 24h summary detail buckets.
    # Totals/groupings are computed in SQL and stay accurate beyond this.
    summary_detail_limit: int = 5000

    # AI narration (optional). Empty key -> deterministic template fallback.
    openai_api_key: str = ""
    openai_model: str = "gpt-5.4-mini"


# The insecure placeholder shipped in .env.example; refused in production.
DEFAULT_WEBHOOK_TOKEN = "dev-secret-change-me"

settings = Settings()
