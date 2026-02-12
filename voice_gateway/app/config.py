from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    PUBLIC_HOST: str = "localhost"
    PUBLIC_PROTOCOL: str = "http"
    VOICE_GATEWAY_PORT: int = 8080
    BACKEND_PORT: int = 8081
    PUBLIC_BASE_URL: str | None = None
    BACKEND_URL: str | None = None
    OPENAI_API_KEY: str = ""
    BACKEND_API_KEY: str = "be_api_key"
    LOG_LEVEL: str = "info"
    OPENAI_REALTIME_MODEL: str = "gpt-4o-realtime-preview-2024-12-17"
    DB_CONNECTION_STRING: str | None = None

    @property
    def public_voice_url(self) -> str:
        return self.PUBLIC_BASE_URL or f"{self.PUBLIC_PROTOCOL}://{self.PUBLIC_HOST}:{self.VOICE_GATEWAY_PORT}"

    @property
    def backend_url(self) -> str:
        return self.BACKEND_URL or f"{self.PUBLIC_PROTOCOL}://{self.PUBLIC_HOST}:{self.BACKEND_PORT}"


settings = Settings()
