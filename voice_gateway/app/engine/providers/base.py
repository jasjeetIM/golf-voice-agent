"""Base interfaces for realtime provider adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ...observability.logger import DbLogger
from .types import ProviderEvent, ProviderSessionInfo


class RealtimeProvider(ABC):
    """Provider contract consumed by provider-agnostic realtime engines."""

    @abstractmethod
    async def start(self) -> ProviderSessionInfo:
        """Initializes provider resources and returns startup metadata."""

    @abstractmethod
    async def send_audio(self, audio_bytes: bytes) -> None:
        """Sends caller audio bytes to provider input."""

    @abstractmethod
    async def events(self) -> AsyncIterator[ProviderEvent]:
        """Yields normalized provider events until provider closes."""

    @abstractmethod
    async def on_output_played(
        self,
        *,
        item_id: str,
        content_index: int,
        byte_count: int,
        mark_id: str,
    ) -> None:
        """Acknowledges that outbound audio was played by Twilio."""

    @abstractmethod
    def set_call_context(self, *, call_id: str | None, logger: DbLogger | None) -> None:
        """Injects call-scoped observability context for tool bridges."""

    @abstractmethod
    async def close(self) -> None:
        """Releases provider resources."""
