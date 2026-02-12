from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    BACKEND_PORT: int = 8081
    BACKEND_API_KEY: str = "be_api_key"
    DB_CONNECTION_STRING: str = "postgresql://postgres:postgres@localhost:5432/golf"
    DB_POOL_MAX: int = 10
    DB_READ_ONLY: bool = False
    LOG_LEVEL: str = "info"


settings = Settings()
