"""Application configuration for the backend service."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed runtime settings for backend APIs and data access."""

    # The repository uses one shared `.env` file for backend, voice gateway, and
    # seed scripts.
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

    # Seed script defaults. These are consumed by backend/scripts/seed_slots.py
    SEED_COURSE_ID: str = "0"
    SEED_COURSE_NAME: str = "Demo Course 0"
    SEED_COURSE_TIMEZONE: str = "America/New_York"
    TEE_TIME_START_HOUR: int = Field(default=7, ge=0, le=23)
    TEE_TIME_END_HOUR: int = Field(default=15, ge=0, le=23)
    SLOT_INTERVAL_MINUTES: int = Field(default=12, gt=0)
    FORWARD_OPEN_TEE_TIME_DAYS: int = Field(default=14, gt=0)
    SLOT_CAPACITY_PLAYERS: int = Field(default=4, gt=0)
    REGULAR_PRICE_CENTS: int = Field(default=10000, ge=0)
    TWILIGHT_PRICE_CENTS: int = Field(default=5000, ge=0)
    TWILIGHT_START_HOUR: int = Field(default=15, ge=0, le=23)


settings = Settings()
