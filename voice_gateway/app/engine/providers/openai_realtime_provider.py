"""OpenAI Realtime provider adapter implementation."""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from agents.realtime import RealtimePlaybackTracker, RealtimeRunner, RealtimeSession
from agents.realtime.model_events import RealtimeModelToolCallEvent

from ...agent.create_agent import create_agent
from ...backend_client import BackendClient
from ...config import settings
from ...mcp.backend_server import BackendMCPServer
from ...observability.logger import DbLogger
from .base import RealtimeProvider
from .types import ProviderEvent, ProviderSessionInfo

_LOGGER = logging.getLogger(__name__)


class OpenAIRealtimeProvider(RealtimeProvider):
    """Realtime provider backed by OpenAI Agents SDK realtime session."""

    def __init__(self) -> None:
        self._playback_tracker = RealtimePlaybackTracker()
        self._session: RealtimeSession | None = None
        self._backend_client: BackendClient | None = None
        self._mcp_server: BackendMCPServer | None = None
        self._agent_name: str | None = None
        self._call_id: str | None = None
        self._logger: DbLogger | None = None

    async def start(self) -> ProviderSessionInfo:
        """Starts OpenAI realtime session and MCP tool bridge resources."""
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required")

        self._backend_client = BackendClient(settings.backend_url, settings.BACKEND_API_KEY)
        self._mcp_server = BackendMCPServer(self._backend_client)
        agent = create_agent(self._mcp_server)
        self._agent_name = getattr(agent, "name", None)

        runner = RealtimeRunner(agent)
        self._session = await runner.run(
            model_config={
                "api_key": settings.OPENAI_API_KEY,
                "initial_model_settings": {
                    "model_name": settings.OPENAI_REALTIME_MODEL,
                    "output_modalities": ["audio"],
                    "input_audio_format": "g711_ulaw",
                    "output_audio_format": "g711_ulaw",
                    "voice": settings.OPENAI_REALTIME_VOICE,
                    "turn_detection": {
                        "type": settings.OPENAI_TURN_DETECTION_TYPE,
                        "interrupt_response": True,
                        "create_response": True,
                    },
                },
                "playback_tracker": self._playback_tracker,
            }
        )
        await self._session.enter()

        return ProviderSessionInfo(
            provider_name="openai",
            component="realtime",
            agent_name=self._agent_name,
            model_name=settings.OPENAI_REALTIME_MODEL,
            external_session_id=None,
            metadata_json={
                "voice": settings.OPENAI_REALTIME_VOICE,
                "turn_detection_type": settings.OPENAI_TURN_DETECTION_TYPE,
            },
        )

    async def send_audio(self, audio_bytes: bytes) -> None:
        """Forwards caller audio bytes to OpenAI realtime session."""
        session = self._require_session()
        await session.send_audio(audio_bytes)

    async def events(self) -> AsyncIterator[ProviderEvent]:
        """Yields normalized events mapped from OpenAI realtime session events."""
        session = self._require_session()
        async for event in session:
            async for mapped in self._map_event(event):
                yield mapped

    async def on_output_played(
        self,
        *,
        item_id: str,
        content_index: int,
        byte_count: int,
        mark_id: str,
    ) -> None:
        """Acknowledges played outbound audio through playback tracker."""
        del mark_id
        self._playback_tracker.on_play_bytes(
            item_id,
            content_index,
            b"\x00" * byte_count,
        )

    def set_call_context(self, *, call_id: str | None, logger: DbLogger | None) -> None:
        """Injects call context into MCP bridge logging hooks."""
        self._call_id = call_id
        self._logger = logger
        if self._mcp_server:
            self._mcp_server.set_call_id(call_id)
            self._mcp_server.set_logger(logger)

    async def close(self) -> None:
        """Closes OpenAI session and backend client resources."""
        if self._session:
            with contextlib.suppress(Exception):
                await self._session.close()
        if self._backend_client:
            with contextlib.suppress(Exception):
                await self._backend_client.close()
        self._session = None
        self._backend_client = None
        self._mcp_server = None

    async def _map_event(self, event: Any) -> AsyncIterator[ProviderEvent]:
        """Maps one OpenAI realtime event to one-or-more ProviderEvents."""
        event_type = getattr(event, "type", "unknown")

        if event_type == "audio":
            yield ProviderEvent(
                event_name="audio_output",
                provider_name="openai",
                external_event_type="audio",
                item_id=event.audio.item_id,
                content_index=event.audio.content_index,
                response_id=getattr(event.audio, "response_id", None),
                audio_bytes=event.audio.data,
                direction="OUT",
            )
            return

        if event_type == "audio_interrupted":
            yield ProviderEvent(
                event_name="audio_interrupted",
                provider_name="openai",
                external_event_type="audio_interrupted",
                item_id=getattr(event, "item_id", None),
                direction="OUT",
            )
            return

        if event_type == "tool_start":
            args_json = self._safe_json_loads(getattr(event, "arguments", None))
            yield ProviderEvent(
                event_name="tool_call_started",
                provider_name="openai",
                external_event_type="tool_start",
                tool_name=event.tool.name,
                arguments_raw=event.arguments,
                arguments_json=args_json,
                agent_name=event.agent.name,
            )
            return

        if event_type == "tool_end":
            args_json = self._safe_json_loads(getattr(event, "arguments", None))
            output_raw = json.dumps(event.output, default=str)
            result_json = event.output if isinstance(event.output, dict) else {"output": str(event.output)}
            yield ProviderEvent(
                event_name="tool_call_finished",
                provider_name="openai",
                external_event_type="tool_end",
                tool_name=event.tool.name,
                arguments_raw=event.arguments,
                arguments_json=args_json,
                result_json=result_json,
                output_raw=output_raw,
                status="SUCCEEDED",
                agent_name=event.agent.name,
            )
            return

        if event_type == "history_added":
            yield ProviderEvent(
                event_name="history_item_added",
                provider_name="openai",
                external_event_type="history_added",
                item_id=event.item.item_id,
                role=getattr(event.item, "role", None),
                item_json=event.item.model_dump(),
            )
            return

        if event_type == "agent_start":
            yield ProviderEvent(
                event_name="agent_turn_started",
                provider_name="openai",
                external_event_type="agent_start",
                agent_name=event.agent.name,
            )
            return

        if event_type == "agent_end":
            yield ProviderEvent(
                event_name="agent_turn_finished",
                provider_name="openai",
                external_event_type="agent_end",
                agent_name=event.agent.name,
            )
            return

        if event_type == "error":
            yield ProviderEvent(
                event_name="provider_error",
                provider_name="openai",
                external_event_type="error",
                error_message=str(getattr(event, "error", "")),
                payload_json={"error": getattr(event, "error", None)},
            )
            return

        if event_type != "raw_model_event":
            return

        raw = event.data
        raw_type = getattr(raw, "type", "unknown")
        raw_payload: dict[str, Any] = {"raw_type": raw_type}
        external_session_id = None

        if isinstance(raw, RealtimeModelToolCallEvent):
            args_json = self._safe_json_loads(raw.arguments)
            yield ProviderEvent(
                event_name="tool_call_started",
                provider_name="openai",
                external_event_type=raw_type,
                tool_name=raw.name,
                tool_call_external_id=raw.call_id,
                arguments_raw=raw.arguments,
                arguments_json=args_json,
            )

        if raw_type in {"session.created", "session.updated"}:
            external_session_id = self._extract_session_id(raw)
            event_name = "session_started" if raw_type == "session.created" else "session_updated"
            yield ProviderEvent(
                event_name=event_name,
                provider_name="openai",
                external_event_type=raw_type,
                external_session_id=external_session_id,
                payload_json=raw_payload,
                direction="SYSTEM",
            )
            return

        if raw_type == "raw_server_event":
            raw_data = getattr(raw, "data", None)
            if isinstance(raw_data, dict):
                server_type = str(raw_data.get("type", "unknown"))
                raw_payload["raw_server_type"] = server_type
                raw_payload["raw_server_summary"] = self._summarize_raw_server_payload(raw_data)
                if settings.VERBOSE_OPENAI_RAW_EVENTS:
                    raw_payload["raw_server_event"] = raw_data

                if server_type in {"session.created", "session.updated"}:
                    session_obj = raw_data.get("session", {})
                    if isinstance(session_obj, dict):
                        value = session_obj.get("id")
                        external_session_id = str(value) if value else None
                    event_name = "session_started" if server_type == "session.created" else "session_updated"
                    yield ProviderEvent(
                        event_name=event_name,
                        provider_name="openai",
                        external_event_type=server_type,
                        external_event_id=raw_data.get("event_id"),
                        external_session_id=external_session_id,
                        payload_json=raw_payload,
                        direction="SYSTEM",
                    )
                    return

                yield ProviderEvent(
                    event_name="raw_event",
                    provider_name="openai",
                    external_event_type=server_type,
                    external_event_id=raw_data.get("event_id"),
                    payload_json=raw_payload,
                    direction="SYSTEM",
                )
                return

        yield ProviderEvent(
            event_name="raw_event",
            provider_name="openai",
            external_event_type=raw_type,
            payload_json=raw_payload,
            direction="SYSTEM",
        )

    @staticmethod
    def _safe_json_loads(data: str | None) -> dict[str, Any]:
        """Parses optional JSON strings into dictionaries."""
        if not data:
            return {}
        try:
            parsed = json.loads(data)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _extract_session_id(raw_event: Any) -> str | None:
        """Extracts session id from OpenAI raw model events."""
        session_obj = getattr(raw_event, "session", None)
        if session_obj is None:
            return None
        if isinstance(session_obj, dict):
            value = session_obj.get("id")
            return str(value) if value else None

        value = getattr(session_obj, "id", None)
        if value:
            return str(value)

        if hasattr(session_obj, "model_dump"):
            dumped = session_obj.model_dump()
            fallback = dumped.get("id")
            return str(fallback) if fallback else None
        return None

    @staticmethod
    def _summarize_raw_server_payload(raw_data: dict[str, Any]) -> dict[str, Any]:
        """Builds a compact summary for high-value OpenAI raw server fields."""
        summary_keys = ("type", "event_id", "response_id", "item_id", "output_index", "content_index")
        summary = {key: raw_data.get(key) for key in summary_keys if key in raw_data}

        response = raw_data.get("response")
        if isinstance(response, dict):
            summary["response_status"] = response.get("status")
            status_details = response.get("status_details")
            if isinstance(status_details, dict):
                summary["response_reason"] = status_details.get("reason")
                status_error = status_details.get("error")
                if isinstance(status_error, dict):
                    summary["response_error_code"] = status_error.get("code")
                    summary["response_error_type"] = status_error.get("type")
            output_modalities = response.get("output_modalities")
            if isinstance(output_modalities, list):
                summary["response_output_modalities"] = output_modalities

        error = raw_data.get("error")
        if isinstance(error, dict):
            summary["error_code"] = error.get("code")
            summary["error_message"] = error.get("message")
            summary["error_type"] = error.get("type")

        session = raw_data.get("session")
        if isinstance(session, dict):
            summary["model"] = session.get("model")
            summary["output_modalities"] = session.get("output_modalities")
            audio = session.get("audio")
            if isinstance(audio, dict):
                output = audio.get("output")
                if isinstance(output, dict):
                    summary["output_voice"] = output.get("voice")
                    output_fmt = output.get("format")
                    if isinstance(output_fmt, dict):
                        summary["output_format"] = output_fmt.get("type")

        return summary

    def _require_session(self) -> RealtimeSession:
        """Returns active realtime session or raises when provider is not started."""
        if self._session is None:
            raise RuntimeError("OpenAIRealtimeProvider.start() must be called before use")
        return self._session
