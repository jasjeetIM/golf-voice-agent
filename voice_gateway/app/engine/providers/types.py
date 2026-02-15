"""Provider-agnostic types for realtime voice provider integrations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utcnow() -> datetime:
    """Returns current UTC wall clock time."""
    return datetime.now(timezone.utc)


@dataclass(slots=True, frozen=True)
class ProviderSessionInfo:
    """Startup metadata returned by a realtime provider.

    Attributes:
        provider_name: Provider identifier (for example, ``openai``).
        component: Logical component name (``realtime`` for V2 realtime flow).
        agent_name: Provider-configured agent name.
        model_name: Primary model identifier.
        external_session_id: Provider-native session identifier when available.
        metadata_json: Optional free-form startup metadata.
    """

    provider_name: str
    component: str = "realtime"
    agent_name: str | None = None
    model_name: str | None = None
    external_session_id: str | None = None
    metadata_json: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ProviderEvent:
    """Normalized provider event consumed by provider-agnostic engines.

    Attributes:
        event_name: Canonical event identifier.
        provider_name: Event source provider.
        component: Logical producer (for example, ``realtime``).
        occurred_at: Event timestamp in UTC.
        external_event_type: Provider-native event type.
        external_event_id: Provider-native event identifier.
        external_session_id: Provider session id when available.
        payload_json: Compact event payload for logging.
        audio_bytes: Audio payload for ``audio_output`` events.
        item_id: Provider item id associated with event.
        content_index: Content index associated with audio/tool output.
        response_id: Provider response id when available.
        tool_name: Tool name for tool lifecycle events.
        tool_call_external_id: Provider tool-call id.
        arguments_raw: Raw tool argument string.
        arguments_json: Parsed tool arguments.
        result_json: Tool output payload.
        output_raw: Raw output string.
        status: Event/tool status.
        error_message: Error text when event represents failure.
        role: Role for history item events.
        item_json: Provider item payload for conversation persistence.
        agent_name: Agent name associated with event.
        turn_index: Optional turn index.
        latency_ms: Optional latency metadata.
        direction: Optional direction label (``IN``/``OUT``/``SYSTEM``).
    """

    event_name: str
    provider_name: str
    component: str = "realtime"
    occurred_at: datetime = field(default_factory=_utcnow)
    external_event_type: str | None = None
    external_event_id: str | None = None
    external_session_id: str | None = None
    payload_json: dict[str, Any] = field(default_factory=dict)
    audio_bytes: bytes | None = None
    item_id: str | None = None
    content_index: int | None = None
    response_id: str | None = None
    tool_name: str | None = None
    tool_call_external_id: str | None = None
    arguments_raw: str | None = None
    arguments_json: dict[str, Any] | None = None
    result_json: dict[str, Any] | None = None
    output_raw: str | None = None
    status: str | None = None
    error_message: str | None = None
    role: str | None = None
    item_json: dict[str, Any] | None = None
    agent_name: str | None = None
    turn_index: int | None = None
    latency_ms: int | None = None
    direction: str | None = None
