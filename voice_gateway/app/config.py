"""Runtime configuration for the voice gateway service."""

from __future__ import annotations

from pydantic import Field
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
        OBSERVABILITY_LOG_LEVEL: Log level for observability internals.
        WEBSOCKETS_LOG_LEVEL: Log level for `websockets` library internals.
        TWILIO_STREAM_LOG_SAMPLE_EVERY_N: Frame sampling cadence when verbose
            stream logging is disabled.
        TWILIO_STARTUP_BUFFER_CHUNKS: Number of initial audio chunks to buffer
            before forwarding caller audio to the realtime session.
        OPENAI_REALTIME_MODEL: Realtime model identifier.
        OPENAI_REALTIME_VOICE: Voice used for synthesized model audio.
        OPENAI_TURN_DETECTION_TYPE: Realtime VAD mode (`server_vad` or
            `semantic_vad`) used for caller turn detection.
        OPENAI_LOG: Log level for OpenAI SDK/Agents/httpx logs.
        VERBOSE_OPENAI_RAW_EVENTS: Enables full raw OpenAI server payload
            logging (high volume).
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
    OBSERVABILITY_LOG_LEVEL: str = "info"
    WEBSOCKETS_LOG_LEVEL: str = "info"
    TWILIO_STREAM_LOG_SAMPLE_EVERY_N: int = Field(default=100, ge=1)
    TWILIO_STARTUP_BUFFER_CHUNKS: int = Field(default=3, ge=0)
    OPENAI_REALTIME_MODEL: str = "gpt-4o-realtime-preview-2024-12-17"
    OPENAI_REALTIME_VOICE: str = "alloy"
    OPENAI_TURN_DETECTION_TYPE: str = "server_vad"
    OPENAI_LOG: str = "info"
    VERBOSE_OPENAI_RAW_EVENTS: bool = False
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
