"""Factory for constructing call-engine implementations."""

from __future__ import annotations

import logging

from .base import CallEngine
from .providers.openai_realtime_provider import OpenAIRealtimeProvider
from .realtime_engine import RealtimeCallEngine
from .types import EngineMode

_LOGGER = logging.getLogger(__name__)


def create_call_engine(
    *,
    mode: str,
) -> CallEngine:
    """Builds the configured call engine.

    Args:
        mode: Requested execution mode (for example ``realtime``).
    Returns:
        A concrete ``CallEngine`` instance.

    Raises:
        NotImplementedError: If pipeline mode is selected before implementation.
        ValueError: If mode is not recognized.
    """
    normalized = mode.strip().lower()
    _LOGGER.debug(
        "Creating call engine from config mode.",
        extra={"requested_mode": mode, "normalized_mode": normalized},
    )
    if normalized == "realtime":
        return RealtimeCallEngine(provider=OpenAIRealtimeProvider())
    if normalized == "pipeline":
        raise NotImplementedError("PipelineCallEngine is not implemented yet")

    raise ValueError(f"Unsupported VOICE_EXECUTION_MODE: {mode}")


def supported_engine_modes() -> tuple[EngineMode, EngineMode]:
    """Returns known execution modes for documentation and validation."""
    return ("realtime", "pipeline")
