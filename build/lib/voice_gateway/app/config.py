"""Runtime configuration for the voice gateway service."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings for voice gateway runtime behavior.

    Values are loaded from environment variables, with `.env` used for local
    development defaults.

    Attributes:
        PUBLIC_HOST: Public hostname used when constructing callback URLs.
        PUBLIC_PROTOCOL: URL scheme (`http` or `https`) for public endpoints.
        VOICE_GATEWAY_PORT: Local port where voice gateway listens.
        BACKEND_PORT: Local backend service port used for default backend URL.
        PUBLIC_BASE_URL: Optional explicit public base URL override.
        BACKEND_URL: Optional explicit backend base URL override.
        OPENAI_API_KEY: API key for realtime model access.
        BACKEND_API_KEY: Bearer token sent to backend tool APIs.
        LOG_LEVEL: Application log verbosity.
        OPENAI_REALTIME_MODEL: Realtime model identifier.
        DB_CONNECTION_STRING: Optional observability database connection string.
        VALIDATE_TWILIO_SIGNATURES: Whether to enforce Twilio signature checks.
        TWILIO_AUTH_TOKEN: Auth token used to validate Twilio signatures.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

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

    # Twilio webhook validation. Keep enabled in production.
    VALIDATE_TWILIO_SIGNATURES: bool = True
    TWILIO_AUTH_TOKEN: str = ""

    @property
    def public_voice_url(self) -> str:
        """Builds the public HTTP base URL used for webhook callbacks.

        Returns:
            External HTTP(S) base URL for Twilio webhook requests.
        """
        return self.PUBLIC_BASE_URL or (
            f"{self.PUBLIC_PROTOCOL}://{self.PUBLIC_HOST}:{self.VOICE_GATEWAY_PORT}"
        )

    @property
    def public_stream_url(self) -> str:
        """Builds the public WS(S) URL used for Twilio media streams.

        Returns:
            Websocket base URL derived from `public_voice_url`.
        """
        return self.public_voice_url.replace("http", "ws", 1)

    @property
    def backend_url(self) -> str:
        """Builds the backend API base URL used by MCP tool calls.

        Returns:
            Backend base URL from explicit override or host/protocol defaults.
        """
        return (
            self.BACKEND_URL or f"{self.PUBLIC_PROTOCOL}://{self.PUBLIC_HOST}:{self.BACKEND_PORT}"
        )


settings = Settings()
