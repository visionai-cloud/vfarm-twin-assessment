"""Runtime configuration, loaded from environment / .env."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./vfarm.db"
    webhook_token: str = "dev-secret-change-me"
    sheet_csv_url: str = "./sample_data/builder_updates.csv"
    sheet_poll_seconds: int = 300


settings = Settings()
