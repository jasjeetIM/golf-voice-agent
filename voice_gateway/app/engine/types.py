"""Shared type definitions for voice call engine abstractions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

EngineMode = Literal["realtime", "pipeline"]

# Callback used by engines to emit Twilio websocket frames.
TwilioOutboundSender = Callable[[dict[str, Any]], Awaitable[None]]

# Callback used by engines to consume Twilio websocket frames.
TwilioInboundMessage = dict[str, Any]
