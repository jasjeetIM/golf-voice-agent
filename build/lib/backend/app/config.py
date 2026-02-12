from __future__ import annotations

"""Application configuration for the backend service."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed runtime settings for backend APIs and data access."""

    # The repository uses one shared `.env` file for backend, voice gateway, and
    # seed scripts. Ignore unknown keys so each service can load only what it
    # needs without failing on unrelated variables.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    BACKEND_PORT: int = Field(default=8081, ge=1, le=65535)
    BACKEND_API_KEY: str = "be_api_key"
    DB_CONNECTION_STRING: str = "postgresql://postgres:postgres@localhost:5432/golf"
    DB_POOL_MAX: int = Field(default=10, ge=1)
    DB_READ_ONLY: bool = False
    LOG_LEVEL: str = "info"


settings = Settings()
