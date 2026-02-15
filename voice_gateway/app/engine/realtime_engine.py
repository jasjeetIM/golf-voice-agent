"""Provider-agnostic realtime call engine.

This engine owns call orchestration, Twilio event routing, and transport-level
buffering while delegating provider-specific behavior to a `RealtimeProvider`.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import logging
import time
from typing import Any

from ..config import settings
from ..observability.logger import DbLogger
from .base import CallEngine
from .providers.base import RealtimeProvider
from .providers.types import ProviderEvent, ProviderSessionInfo
from .types import TwilioInboundMessage, TwilioOutboundSender

_LOGGER = logging.getLogger(__name__)


class RealtimeCallEngine(CallEngine):
    """Routes Twilio audio/events through a provider-backed realtime flow."""

    def __init__(self, *, provider: RealtimeProvider) -> None:
        """Initializes provider-agnostic engine state.

        Args:
            provider: Realtime provider adapter implementation.
        """
        self._provider = provider
        self._provider_info: ProviderSessionInfo | None = None
        self._emit_twilio_message: TwilioOutboundSender | None = None

        self._provider_event_loop_task: asyncio.Task[None] | None = None
        self._buffer_flush_task: asyncio.Task[None] | None = None

        self._is_shutting_down = False
        self._stop_requested = False

        self._stream_sid: str | None = None
        self._call_id: str | None = None
        self._provider_session_id: str | None = None
        self._logger: DbLogger | None = None

        self._chunk_length_s = 0.05
        self._sample_rate_hz = 8000
        self._buffer_size_bytes = int(self._sample_rate_hz * self._chunk_length_s)
        self._caller_audio_buffer = bytearray()
        self._last_agent_audio_send_time = time.time()
        self._startup_buffer_chunks = settings.TWILIO_STARTUP_BUFFER_CHUNKS
        self._startup_audio_buffer = bytearray()
        self._startup_audio_warmed = self._startup_buffer_chunks == 0

        self._mark_counter = 0
        self._twilio_mark_playback_map: dict[str, tuple[str, int, int]] = {}

        self._twilio_inbound_audio_frames = 0
        self._twilio_inbound_audio_bytes = 0
        self._agent_input_audio_chunks = 0
        self._agent_input_audio_bytes = 0
        self._agent_output_audio_chunks = 0
        self._agent_output_audio_bytes = 0
        self._provider_event_counts: dict[str, int] = {}
        self._turn_index = 0
        self._turn_agent_output_audio_chunks = 0
        self._turn_agent_output_audio_bytes = 0
        self._turn_started_monotonic: float | None = None

    async def start(self, *, emit_twilio_message: TwilioOutboundSender) -> None:
        """Starts provider resources and internal engine background tasks."""
        if self._provider_event_loop_task is not None:
            _LOGGER.debug("RealtimeCallEngine.start() called after startup; ignoring.")
            return

        self._emit_twilio_message = emit_twilio_message
        self._provider_info = await self._provider.start()

        self._provider_event_loop_task = asyncio.create_task(self._provider_event_loop())
        self._buffer_flush_task = asyncio.create_task(self._buffer_flush_loop())
        _LOGGER.debug(
            "RealtimeCallEngine started.",
            extra={
                "provider_name": self._provider_info.provider_name,
                "component": self._provider_info.component,
                "model_name": self._provider_info.model_name,
            },
        )

    async def handle_twilio_message(self, message: TwilioInboundMessage) -> bool:
        """Processes one inbound Twilio websocket message.

        Returns:
            ``True`` to continue processing Twilio websocket input, otherwise
            ``False`` to terminate call processing.
        """
        if self._stop_requested or self._is_shutting_down:
            return False

        event = str(message.get("event") or "")
        if event == "start":
            await self._handle_start_event(message)
            return True
        if event == "media":
            await self._handle_media_event(message)
            return True
        if event == "mark":
            await self._handle_mark_event(message)
            return True
        if event == "stop":
            await self._try_log_call_event(
                event_name="stop",
                payload=message,
                direction="IN",
                source="TWILIO",
                transport_provider="twilio",
            )
            self._stop_requested = True
            return False

        await self._try_log_call_event(
            event_name=event or "unknown",
            payload=message,
            direction="IN",
            source="TWILIO",
            transport_provider="twilio",
        )
        return True

    async def shutdown(self) -> None:
        """Stops background tasks and closes provider resources."""
        if self._is_shutting_down:
            return
        self._is_shutting_down = True
        self._stop_requested = True

        await self._cancel_task(self._provider_event_loop_task)
        await self._cancel_task(self._buffer_flush_task)

        with contextlib.suppress(Exception):
            await self._provider.close()

        self._log_call_summary()
        if self._logger:
            with contextlib.suppress(Exception):
                await self._logger.finalize_call()

        self._emit_twilio_message = None
        self._provider_event_loop_task = None
        self._buffer_flush_task = None

    async def _cancel_task(self, task: asyncio.Task[None] | None) -> None:
        """Cancels and drains one task if active."""
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
        if task and task is not asyncio.current_task():
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def _provider_event_loop(self) -> None:
        """Consumes provider events and applies engine routing and logging."""
        try:
            async for event in self._provider.events():
                await self._handle_provider_event(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Provider event loop failed.")
            await self._log_internal_error("provider_event_loop_failed")
            self._stop_requested = True

    async def _buffer_flush_loop(self) -> None:
        """Flushes stale caller-audio fragments to reduce interaction latency."""
        try:
            while not self._is_shutting_down:
                await asyncio.sleep(self._chunk_length_s)
                if self._should_flush_caller_audio_buffer():
                    await self._flush_caller_audio_buffer()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Audio buffer flush loop failed.")
            await self._log_internal_error("audio_buffer_flush_loop_failed")
            self._stop_requested = True

    def _should_flush_caller_audio_buffer(self) -> bool:
        """Returns whether buffered caller audio is stale and should be flushed."""
        if not self._caller_audio_buffer:
            return False
        stale_seconds = self._chunk_length_s * 2
        return time.time() - self._last_agent_audio_send_time > stale_seconds

    async def _handle_start_event(self, message: dict[str, Any]) -> None:
        """Initializes call-scoped context when Twilio stream starts."""
        start_data = message.get("start", {})
        self._stream_sid = start_data.get("streamSid")
        call_sid = start_data.get("callSid")

        if not call_sid:
            _LOGGER.debug("Twilio start event missing callSid.")
            return

        provider_info = self._require_provider_info()
        self._call_id = call_sid
        self._logger = DbLogger(call_sid)

        await self._logger.ensure_call(
            from_number=(
                start_data.get("customParameters", {}).get("from")
                or start_data.get("from")
                or ""
            ),
            to_number=(
                start_data.get("customParameters", {}).get("to")
                or start_data.get("to")
                or ""
            ),
            engine_mode=settings.VOICE_EXECUTION_MODE,
            agent_provider=provider_info.provider_name,
            agent_model=provider_info.model_name,
            stt_provider=None,
            stt_model=None,
            tts_provider=None,
            tts_model=None,
            realtime_provider=provider_info.provider_name,
            realtime_model=provider_info.model_name,
        )

        self._provider.set_call_context(call_id=call_sid, logger=self._logger)

        await self._ensure_provider_session(
            external_session_id=provider_info.external_session_id,
            metadata_json=provider_info.metadata_json,
        )

        await self._logger.log_call_event(
            event_name="start",
            payload=message,
            direction="IN",
            source="TWILIO",
            transport_provider="twilio",
        )

    async def _handle_media_event(self, message: dict[str, Any]) -> None:
        """Buffers inbound Twilio media and forwards chunks to provider."""
        media = message.get("media", {})
        payload = media.get("payload", "")
        if not payload:
            return

        try:
            ulaw_bytes = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            await self._log_internal_error("invalid_twilio_media_payload")
            return

        self._twilio_inbound_audio_frames += 1
        self._twilio_inbound_audio_bytes += len(ulaw_bytes)
        self._caller_audio_buffer.extend(ulaw_bytes)

        if len(self._caller_audio_buffer) >= self._buffer_size_bytes:
            await self._flush_caller_audio_buffer()

    async def _handle_mark_event(self, message: dict[str, Any]) -> None:
        """Processes Twilio mark acknowledgements for played outbound audio."""
        mark_data = message.get("mark", {})
        mark_id = mark_data.get("name", "")
        if mark_id not in self._twilio_mark_playback_map:
            return

        item_id, item_content_index, byte_count = self._twilio_mark_playback_map[mark_id]
        await self._provider.on_output_played(
            item_id=item_id,
            content_index=item_content_index,
            byte_count=byte_count,
            mark_id=mark_id,
        )
        del self._twilio_mark_playback_map[mark_id]

    async def _flush_caller_audio_buffer(self) -> None:
        """Flushes caller audio buffer to provider input audio stream."""
        if not self._caller_audio_buffer:
            return

        audio_chunk = bytes(self._caller_audio_buffer)
        self._caller_audio_buffer.clear()
        self._last_agent_audio_send_time = time.time()

        if not self._startup_audio_warmed:
            self._startup_audio_buffer.extend(audio_chunk)
            warmup_target_bytes = self._buffer_size_bytes * self._startup_buffer_chunks
            if len(self._startup_audio_buffer) < warmup_target_bytes:
                return
            audio_chunk = bytes(self._startup_audio_buffer)
            self._startup_audio_buffer.clear()
            self._startup_audio_warmed = True

        await self._provider.send_audio(audio_chunk)
        self._agent_input_audio_chunks += 1
        self._agent_input_audio_bytes += len(audio_chunk)

    async def _handle_provider_event(self, event: ProviderEvent) -> None:
        """Routes one normalized provider event to Twilio and observability."""
        await self._update_provider_session_from_event(event)
        self._update_provider_diagnostics(event)
        active_turn_index = self._resolve_turn_index(event.turn_index)

        if self._logger and event.event_name != "audio_output":
            await self._logger.log_session_event(
                event_name=event.event_name,
                component=event.component,
                provider_name=event.provider_name,
                payload=event.payload_json,
                external_event_type=event.external_event_type,
                external_event_id=event.external_event_id,
                direction=event.direction,
                item_id=event.item_id,
                tool_call_id=event.tool_call_external_id,
                agent_name=event.agent_name,
                turn_index=active_turn_index,
                latency_ms=event.latency_ms,
            )

        if event.event_name == "audio_output":
            await self._emit_audio_to_twilio(event)
            return

        if event.event_name == "audio_interrupted" and self._stream_sid:
            await self._emit_twilio_message_payload({"event": "clear", "streamSid": self._stream_sid})
            return

        if self._logger and event.event_name == "tool_call_started" and event.tool_name:
            await self._logger.log_tool_call(
                tool_name=event.tool_name,
                args_json=event.arguments_json or {},
                result_json=None,
                status="RUNNING",
                error_message=None,
                tool_call_external_id=event.tool_call_external_id,
                arguments_raw=event.arguments_raw,
                agent_name=event.agent_name,
                provider_name=event.provider_name,
                component=event.component,
                turn_index=active_turn_index,
            )
            return

        if self._logger and event.event_name == "tool_call_finished" and event.tool_name:
            await self._logger.log_tool_call(
                tool_name=event.tool_name,
                args_json=event.arguments_json or {},
                result_json=event.result_json,
                status=event.status or "SUCCEEDED",
                error_message=event.error_message,
                tool_call_external_id=event.tool_call_external_id,
                arguments_raw=event.arguments_raw,
                output_raw=event.output_raw,
                agent_name=event.agent_name,
                latency_ms=event.latency_ms,
                provider_name=event.provider_name,
                component=event.component,
                turn_index=active_turn_index,
            )
            return

        if self._logger and event.event_name == "history_item_added" and event.item_id:
            await self._logger.upsert_conversation_item(
                external_item_id=event.item_id,
                component=event.component,
                provider_name=event.provider_name,
                role=event.role,
                modality="audio" if event.audio_bytes else "text",
                item_type=(event.item_json or {}).get("type") if event.item_json else None,
                status=(event.item_json or {}).get("status") if event.item_json else None,
                content=event.item_json or {},
                tool_call_id=event.tool_call_external_id,
                tool_name=event.tool_name,
            )

    async def _emit_audio_to_twilio(self, event: ProviderEvent) -> None:
        """Emits provider audio output as Twilio media + mark frames."""
        if not self._stream_sid or not event.audio_bytes:
            return

        encoded_audio = base64.b64encode(event.audio_bytes).decode("utf-8")
        self._agent_output_audio_chunks += 1
        self._agent_output_audio_bytes += len(event.audio_bytes)
        self._turn_agent_output_audio_chunks += 1
        self._turn_agent_output_audio_bytes += len(event.audio_bytes)

        await self._emit_twilio_message_payload(
            {
                "event": "media",
                "streamSid": self._stream_sid,
                "media": {"payload": encoded_audio},
            }
        )

        self._mark_counter += 1
        mark_id = str(self._mark_counter)
        self._twilio_mark_playback_map[mark_id] = (
            event.item_id or "",
            event.content_index or 0,
            len(event.audio_bytes),
        )
        await self._emit_twilio_message_payload(
            {
                "event": "mark",
                "streamSid": self._stream_sid,
                "mark": {"name": mark_id},
            }
        )

    async def _emit_twilio_message_payload(self, payload: dict[str, Any]) -> None:
        """Emits one Twilio JSON payload through registered transport callback."""
        if not self._emit_twilio_message:
            return
        await self._emit_twilio_message(payload)

    async def _ensure_provider_session(
        self,
        *,
        external_session_id: str | None,
        metadata_json: dict[str, Any] | None = None,
    ) -> None:
        """Ensures provider session row exists and caches provider_session_id."""
        if not self._logger:
            return
        info = self._require_provider_info()
        provider_session_id = await self._logger.ensure_provider_session(
            component=info.component,
            provider_name=info.provider_name,
            external_session_id=external_session_id,
            model=info.model_name,
            metadata_json=metadata_json,
        )
        if provider_session_id:
            self._provider_session_id = provider_session_id

    async def _update_provider_session_from_event(self, event: ProviderEvent) -> None:
        """Backfills provider session context when event carries session id."""
        if not self._logger:
            return
        if not event.external_session_id:
            return
        await self._ensure_provider_session(
            external_session_id=event.external_session_id,
            metadata_json={"source_event": event.event_name},
        )

    async def _try_log_call_event(
        self,
        *,
        event_name: str,
        payload: dict[str, Any],
        direction: str,
        source: str,
        transport_provider: str | None = None,
    ) -> None:
        """Writes call event records when logger context is available."""
        if not self._logger:
            return
        await self._logger.log_call_event(
            event_name=event_name,
            payload=payload,
            direction=direction,
            source=source,
            transport_provider=transport_provider,
        )

    async def _log_internal_error(self, error_code: str) -> None:
        """Writes normalized internal error call event."""
        await self._try_log_call_event(
            event_name="gateway_error",
            payload={"error_code": error_code},
            direction="SYSTEM",
            source="VOICE_GATEWAY",
            transport_provider="voice_gateway",
        )

    def _update_provider_diagnostics(self, event: ProviderEvent) -> None:
        """Updates lightweight event counters for per-call diagnostics."""
        self._provider_event_counts[event.event_name] = self._provider_event_counts.get(event.event_name, 0) + 1

        if event.event_name == "agent_turn_started":
            self._turn_index += 1
            self._turn_agent_output_audio_chunks = 0
            self._turn_agent_output_audio_bytes = 0
            self._turn_started_monotonic = time.monotonic()
            return

        if event.event_name == "agent_turn_finished" and self._turn_started_monotonic is not None:
            duration_ms = int((time.monotonic() - self._turn_started_monotonic) * 1000)
            _LOGGER.debug(
                "Agent turn ended turn_index=%d duration_ms=%d audio_chunks=%d audio_bytes=%d",
                self._turn_index,
                duration_ms,
                self._turn_agent_output_audio_chunks,
                self._turn_agent_output_audio_bytes,
            )

    def _log_call_summary(self) -> None:
        """Logs one compact end-of-call summary for diagnostics."""
        _LOGGER.debug(
            "Call summary call_id=%s twilio_in_frames=%d twilio_in_bytes=%d "
            "agent_in_chunks=%d agent_in_bytes=%d agent_out_chunks=%d agent_out_bytes=%d",
            self._call_id,
            self._twilio_inbound_audio_frames,
            self._twilio_inbound_audio_bytes,
            self._agent_input_audio_chunks,
            self._agent_input_audio_bytes,
            self._agent_output_audio_chunks,
            self._agent_output_audio_bytes,
        )
        if self._provider_event_counts:
            top_events = sorted(self._provider_event_counts.items(), key=lambda pair: pair[1], reverse=True)[:12]
            _LOGGER.debug("Provider event counts call_id=%s counts=%s", self._call_id, top_events)

    def _require_provider_info(self) -> ProviderSessionInfo:
        """Returns provider startup metadata or raises if not started."""
        if self._provider_info is None:
            raise RuntimeError("RealtimeCallEngine.start() must be called before usage")
        return self._provider_info

    def _resolve_turn_index(self, event_turn_index: int | None) -> int | None:
        """Returns best-available turn index for provider/session logs."""
        if event_turn_index is not None:
            return event_turn_index
        if self._turn_index > 0:
            return self._turn_index
        return None
