"""Base abstractions for voice call execution engines."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .types import TwilioInboundMessage, TwilioOutboundSender


class CallEngine(ABC):
    """Interface implemented by all call execution engines."""

    @abstractmethod
    async def start(self, *, emit_twilio_message: TwilioOutboundSender) -> None:
        """Starts engine resources and background processing."""

    @abstractmethod
    async def handle_twilio_message(self, message: TwilioInboundMessage) -> bool:
        """Processes one Twilio websocket message.

        Returns:
            ``True`` if transport should continue reading messages, otherwise
            ``False`` to indicate call termination.
        """

    @abstractmethod
    async def shutdown(self) -> None:
        """Releases engine-owned resources."""
