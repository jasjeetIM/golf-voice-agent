"""Twilio websocket bridge for realtime audio, tools, and observability.

This module translates data in both directions:
1. Twilio Media Stream websocket events -> OpenAI realtime session input.
2. OpenAI realtime output events -> Twilio websocket media/control events.
3. Realtime/tool events -> observability database rows through ``DbLogger``.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import logging
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from agents.realtime import (
    RealtimePlaybackTracker,
    RealtimeRunner,
    RealtimeSession,
    RealtimeSessionEvent,
)
from agents.realtime.model_events import RealtimeModelToolCallEvent

from ..agent.create_agent import create_agent
from ..backend_client import BackendClient
from ..config import settings
from ..mcp.backend_server import BackendMCPServer
from ..observability.logger import DbLogger

_LOGGER = logging.getLogger(__name__)


class TwilioHandler:
    """Coordinates Twilio media events with realtime model interactions.

    Usage pattern:
    1. ``main.py`` creates one ``TwilioHandler`` per websocket connection.
    2. ``start()`` is called once to initialize model + background tasks.
    3. ``wait_until_done()`` blocks while Twilio messages are received.
    4. ``shutdown()`` is called in a ``finally`` block to release resources.

    Background tasks started by ``start()``:
    - ``_message_loop_task``: Reads inbound Twilio websocket messages.
    - ``_realtime_loop_task``: Reads outbound realtime model events.
    - ``_buffer_flush_task``: Flushes partial audio buffers on a timer.

    Database logging behavior:
    - After a Twilio ``start`` event, a ``DbLogger`` is attached.
    - Incoming and outgoing call-level events are written via
      ``DbLogger.log_call_event``.
    - Realtime session/tool/history events are normalized and written via
      ``DbLogger.log_session_event``, ``DbLogger.log_tool_call``, and
      ``DbLogger.upsert_realtime_item``.
    - MCP request/response logging is performed by ``BackendMCPServer`` once
      this handler injects the logger and call id into that server.
    """

    def __init__(self, websocket: WebSocket):
        """Initializes per-call state for websocket handling.

        Args:
            websocket: Active Twilio websocket connection.
        """
        # Transport and model objects.
        self.websocket = websocket
        self.session: RealtimeSession | None = None
        self.playback_tracker = RealtimePlaybackTracker()

        # These are created in ``start()`` and cancelled in ``shutdown()``.
        self._message_loop_task: asyncio.Task[None] | None = None
        self._realtime_loop_task: asyncio.Task[None] | None = None
        self._buffer_flush_task: asyncio.Task[None] | None = None

        # Audio buffering settings tuned for Twilio 8kHz mulaw.
        self.CHUNK_LENGTH_S = 0.05
        self.SAMPLE_RATE = 8000
        self.BUFFER_SIZE_BYTES = int(self.SAMPLE_RATE * self.CHUNK_LENGTH_S)

        # Stream metadata from Twilio ``start`` event.
        self._stream_sid: str | None = None

        # Inbound caller audio buffer before forwarding to realtime model.
        self._audio_buffer = bytearray()
        self._last_buffer_send_time = time.time()

        # Outbound playback bookkeeping for Twilio mark acknowledgements.
        self._mark_counter = 0
        self._mark_data: dict[str, tuple[str, int, int]] = {}

        # Call/session context used for logging and downstream tool calls.
        self._call_id: str | None = None
        self._session_id: str | None = None
        self._logger: DbLogger | None = None
        self._backend_client: BackendClient | None = None
        self._mcp_server: BackendMCPServer | None = None

        # Set to True during shutdown to stop loops and prevent duplicate close.
        self._is_shutting_down = False

        # Maps ``(tool_name, arguments_raw_json)`` to model tool call ids so we
        # can match ``tool_end`` rows back to the corresponding ``tool_start``.
        self._pending_tool_calls: dict[tuple[str, str], list[str]] = {}

    async def start(self) -> None:
        """Starts realtime session and websocket background loops.

        Why this exists:
        - Establishes all dependencies before any task begins consuming data.
        - Ensures a deterministic startup sequence so loops never run with
          uninitialized clients/session references.

        Startup order:
        1. Build backend client and MCP server for tool invocations.
        2. Build agent and open realtime session.
        3. Accept Twilio websocket.
        4. Start three background loops:
           - ``_realtime_loop_task``: model events -> Twilio output/logging.
           - ``_message_loop_task``: Twilio input -> model audio/logging.
           - ``_buffer_flush_task``: periodic flush of partial audio chunks.

        Raises:
            ValueError: If ``OPENAI_API_KEY`` is not configured.
        """
        # Tool calls from the model are proxied through this client/server pair.
        self._backend_client = BackendClient(settings.backend_url, settings.BACKEND_API_KEY)
        self._mcp_server = BackendMCPServer(self._backend_client, logger=self._logger)
        agent = create_agent(self._mcp_server)

        # Fail fast before opening transports if required credentials are absent.
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required")

        # Create and enter realtime session before accepting websocket messages.
        runner = RealtimeRunner(agent)
        self.session = await runner.run(
            model_config={
                "api_key": settings.OPENAI_API_KEY,
                "initial_model_settings": {
                    "model_name": settings.OPENAI_REALTIME_MODEL,
                    "input_audio_format": "g711_ulaw",
                    "output_audio_format": "g711_ulaw",
                    "turn_detection": {
                        "type": "server_vad",
                        "interrupt_response": True,
                        "create_response": True,
                    },
                    "voice": "cove",
                },
                "playback_tracker": self.playback_tracker,
            }
        )
        await self.session.enter()

        # Accept websocket only after session is ready to consume audio.
        await self.websocket.accept()

        # Start all concurrent loops that drive streaming behavior.
        self._realtime_loop_task = asyncio.create_task(self._realtime_session_loop())
        self._message_loop_task = asyncio.create_task(self._twilio_message_loop())
        self._buffer_flush_task = asyncio.create_task(self._buffer_flush_loop())

    async def wait_until_done(self) -> None:
        """Waits on Twilio websocket message consumption until call ends.

        This method intentionally waits on ``_message_loop_task`` because that
        task blocks on ``websocket.receive_text()`` and therefore naturally
        represents "the call is still alive and Twilio is still sending data."

        Once message consumption stops (disconnect, stop event, or error), this
        method always calls ``shutdown()`` in ``finally`` to guarantee cleanup.
        """
        if not self._message_loop_task:
            return
        try:
            await self._message_loop_task
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Idempotently tears down tasks, session, websocket, and HTTP client.

        Why this exists:
        - Centralizes all teardown behavior so every failure path can safely
          trigger exactly one cleanup sequence.
        - Prevents leaked tasks/sockets when one component fails first.

        Shutdown order:
        1. Mark ``_is_shutting_down`` to stop loops and prevent reentry.
        2. Close realtime session to stop model event production.
        3. Cancel and await all background tasks.
        4. Close backend HTTP client.
        5. Close websocket (if still connected).
        """
        if self._is_shutting_down:
            return
        self._is_shutting_down = True

        # Stop realtime transport first so it cannot enqueue new work.
        if self.session:
            with contextlib.suppress(Exception):
                await self.session.close()

        # Ensure all loop tasks exit before releasing network resources.
        await self._cancel_background_tasks()

        # Release backend HTTP connection pool resources.
        if self._backend_client:
            with contextlib.suppress(Exception):
                await self._backend_client.close()

        # Close Twilio websocket if it has not already disconnected.
        if self.websocket.client_state != WebSocketState.DISCONNECTED:
            with contextlib.suppress(Exception):
                await self.websocket.close()

    async def _cancel_background_tasks(self) -> None:
        """Cancels and awaits all handler-owned background tasks.

        The current task is excluded to avoid self-cancellation and self-await
        deadlocks when shutdown is initiated from inside one of these tasks.
        """
        current = asyncio.current_task()
        tasks = [self._realtime_loop_task, self._message_loop_task, self._buffer_flush_task]

        # Signal cancellation.
        for task in tasks:
            if task and task is not current and not task.done():
                task.cancel()

        # Drain completion for deterministic cleanup.
        for task in tasks:
            if task and task is not current:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    async def _realtime_session_loop(self) -> None:
        """Consumes realtime model events and handles outbound behavior.

        This loop drives assistant output to Twilio and session-level logging.
        """
        assert self.session is not None
        try:
            async for event in self.session:
                await self._handle_realtime_event(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Realtime session loop failed.")
            await self._log_internal_error("realtime_session_loop_failed")
            await self.shutdown()

    async def _twilio_message_loop(self) -> None:
        """Consumes inbound Twilio websocket messages until connection ends.

        This is the "source of truth" loop for call liveness because it waits
        directly on Twilio frames.
        """
        try:
            while not self._is_shutting_down:
                message_text = await self.websocket.receive_text()
                try:
                    message = json.loads(message_text)
                except json.JSONDecodeError:
                    _LOGGER.warning("Received non-JSON message from Twilio.")
                    await self._log_internal_error("invalid_twilio_message_json")
                    continue
                await self._handle_twilio_message(message)
        except asyncio.CancelledError:
            raise
        except WebSocketDisconnect:
            _LOGGER.info("Twilio websocket disconnected.")
        except Exception:
            _LOGGER.exception("Twilio message loop failed.")
            await self._log_internal_error("twilio_message_loop_failed")
            await self.shutdown()

    async def _handle_realtime_event(self, event: RealtimeSessionEvent) -> None:
        """Routes one realtime event to Twilio output and observability.

        Args:
            event: Realtime event emitted by the OpenAI session.
        """
        # Capture session id early so all subsequent logs include it.
        self._capture_session_id_from_event(event)

        # Persist normalized event details when logger is available.
        if self._logger:
            await self._log_session_event(event)

        if event.type == "audio":
            # Do not send output before Twilio has provided stream metadata.
            if not self._stream_sid:
                _LOGGER.debug("Dropping model audio before Twilio streamSid is available.")
                return

            # Convert raw mulaw bytes to base64 payload expected by Twilio.
            base64_audio = base64.b64encode(event.audio.data).decode("utf-8")
            await self._try_log_call_event(
                event_type="media",
                payload={"bytes": len(event.audio.data), "item_id": event.audio.item_id},
                direction="OUT",
                source="OPENAI",
            )
            await self._send_twilio_json(
                {
                    "event": "media",
                    "streamSid": self._stream_sid,
                    "media": {"payload": base64_audio},
                }
            )

            # Store mark metadata so future Twilio mark acknowledgements can be
            # translated into playback tracker progress.
            self._mark_counter += 1
            mark_id = str(self._mark_counter)
            self._mark_data[mark_id] = (
                event.audio.item_id,
                event.audio.content_index,
                len(event.audio.data),
            )
            await self._send_twilio_json(
                {
                    "event": "mark",
                    "streamSid": self._stream_sid,
                    "mark": {"name": mark_id},
                }
            )
        elif event.type == "audio_interrupted":
            if not self._stream_sid:
                return
            # Instruct Twilio to clear queued audio if model was interrupted.
            await self._try_log_call_event(
                event_type="clear",
                payload={"item_id": event.item_id},
                direction="OUT",
                source="OPENAI",
            )
            await self._send_twilio_json({"event": "clear", "streamSid": self._stream_sid})

    async def _handle_twilio_message(self, message: dict[str, Any]) -> None:
        """Routes inbound Twilio event payloads by event type.

        Args:
            message: Parsed Twilio websocket JSON event.
        """
        event = message.get("event")

        # Log every inbound frame category for call-level auditing.
        await self._try_log_call_event(
            event_type=event or "unknown",
            payload=message,
            direction="IN",
            source="TWILIO",
        )

        if event == "start":
            await self._handle_start_event(message)
            return
        if event == "media":
            await self._handle_media_event(message)
            return
        if event == "mark":
            await self._handle_mark_event(message)
            return
        if event == "stop":
            await self.shutdown()

    async def _handle_start_event(self, message: dict[str, Any]) -> None:
        """Initializes call-scoped context from Twilio ``start`` event.

        Args:
            message: Twilio start event payload.
        """
        start_data = message.get("start", {})
        self._stream_sid = start_data.get("streamSid")
        call_sid = start_data.get("callSid")

        # Without callSid, we cannot bind call-level logging or tool context.
        if not call_sid:
            return

        # Create per-call logger and wire the same call context into MCP tools.
        self._call_id = call_sid
        self._logger = DbLogger(call_sid, session_id=self._session_id)
        if self._mcp_server:
            self._mcp_server.set_logger(self._logger)
            self._mcp_server.set_call_id(call_sid)

        # Ensure the parent call row exists before appending child event rows.
        await self._logger.ensure_call(
            from_number=start_data.get("customParameters", {}).get("from", ""),
            to_number=start_data.get("customParameters", {}).get("to", ""),
        )
        await self._logger.log_call_event(
            event_type="start",
            payload=message,
            direction="IN",
            source="TWILIO",
        )

    async def _handle_media_event(self, message: dict[str, Any]) -> None:
        """Buffers caller media payloads and flushes fixed-size chunks.

        Args:
            message: Twilio media event payload.
        """
        media = message.get("media", {})
        payload = media.get("payload", "")
        if not payload or not self.session:
            return

        # Reject malformed base64 to avoid crashing the message loop.
        try:
            ulaw_bytes = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            _LOGGER.warning("Received invalid base64 media payload from Twilio.")
            await self._log_internal_error("invalid_twilio_media_payload")
            return

        self._audio_buffer.extend(ulaw_bytes)
        if len(self._audio_buffer) >= self.BUFFER_SIZE_BYTES:
            await self._flush_audio_buffer()

    async def _handle_mark_event(self, message: dict[str, Any]) -> None:
        """Applies Twilio playback mark acknowledgements.

        Args:
            message: Twilio mark event payload.
        """
        mark_data = message.get("mark", {})
        mark_id = mark_data.get("name", "")
        if mark_id in self._mark_data:
            item_id, item_content_index, byte_count = self._mark_data[mark_id]
            audio_bytes = b"\x00" * byte_count
            self.playback_tracker.on_play_bytes(item_id, item_content_index, audio_bytes)
            del self._mark_data[mark_id]

    async def _flush_audio_buffer(self) -> None:
        """Flushes buffered caller audio into the realtime session."""
        if not self._audio_buffer or not self.session:
            return
        buffer_data = bytes(self._audio_buffer)
        self._audio_buffer.clear()
        self._last_buffer_send_time = time.time()
        await self.session.send_audio(buffer_data)

    async def _buffer_flush_loop(self) -> None:
        """Periodically flushes stale partial buffers to minimize latency.

        This loop prevents short trailing audio fragments from waiting forever
        when the buffer never reaches ``BUFFER_SIZE_BYTES``.
        """
        try:
            while not self._is_shutting_down:
                await asyncio.sleep(self.CHUNK_LENGTH_S)
                stale_buffer = time.time() - self._last_buffer_send_time > self.CHUNK_LENGTH_S * 2
                if self._audio_buffer and stale_buffer:
                    await self._flush_audio_buffer()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Audio buffer flush loop failed.")
            await self._log_internal_error("audio_buffer_flush_loop_failed")
            await self.shutdown()

    async def _send_twilio_json(self, payload: dict[str, Any]) -> None:
        """Serializes and sends one JSON message to Twilio websocket.

        Args:
            payload: JSON-serializable Twilio frame.
        """
        await self.websocket.send_text(json.dumps(payload))

    async def _try_log_call_event(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        direction: str,
        source: str,
    ) -> None:
        """Writes a call event only when logger context is available.

        Args:
            event_type: Normalized event label.
            payload: Event payload body.
            direction: ``IN`` / ``OUT`` / ``SYSTEM``.
            source: Source system (for example ``TWILIO`` or ``OPENAI``).
        """
        if not self._logger:
            return
        await self._logger.log_call_event(
            event_type=event_type,
            payload=payload,
            direction=direction,
            source=source,
        )

    async def _log_internal_error(self, error_code: str) -> None:
        """Writes a normalized internal error event for diagnostics.

        Args:
            error_code: Stable code identifying failure category.
        """
        await self._try_log_call_event(
            event_type="gateway_error",
            payload={"error_code": error_code},
            direction="SYSTEM",
            source="VOICE_GATEWAY",
        )

    async def _log_session_event(self, event: RealtimeSessionEvent) -> None:
        """Maps realtime events into normalized observability records.

        Args:
            event: Realtime session event to log.
        """
        if not self._logger:
            return

        def _safe_json_loads(data: str | None) -> dict[str, Any]:
            """Parses tool argument JSON defensively."""
            if not data:
                return {}
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return {}

        payload: dict[str, Any] = {"type": event.type}
        item_id: str | None = None
        tool_call_id: str | None = None
        agent_name: str | None = None
        direction = "SYSTEM"

        if event.type == "raw_model_event":
            raw = event.data
            payload["raw_type"] = raw.type
            if raw.type in {"session.created", "session.updated"} and self._session_id:
                payload["session_id"] = self._session_id

            if isinstance(raw, RealtimeModelToolCallEvent):
                # Persist tool start details and remember the tool-call id so we
                # can correlate it with the eventual ``tool_end`` event.
                tool_call_id = raw.call_id
                payload.update({"tool_name": raw.name, "arguments": raw.arguments})
                key = (raw.name, raw.arguments)
                self._pending_tool_calls.setdefault(key, []).append(raw.call_id)
                await self._logger.log_tool_call(
                    tool_name=raw.name,
                    args_json=_safe_json_loads(raw.arguments),
                    result_json=None,
                    status="RUNNING",
                    error_message=None,
                    tool_call_external_id=raw.call_id,
                    arguments_raw=raw.arguments,
                    agent_name=agent_name,
                )

            # Maintain a latest snapshot of realtime items for debugging/tracing.
            item_id = getattr(raw, "item_id", None)
            if raw.type == "item_updated" and hasattr(raw, "item"):
                try:
                    await self._logger.upsert_realtime_item(
                        item_id=raw.item.item_id,
                        content=raw.item.model_dump(),
                    )
                except Exception:
                    _LOGGER.debug("Failed to upsert item_updated realtime item.", exc_info=True)
        elif event.type == "tool_start":
            payload.update({"tool": event.tool.name, "arguments": event.arguments})
            direction = "TOOL"
        elif event.type == "tool_end":
            payload.update(
                {"tool": event.tool.name, "arguments": event.arguments, "output": event.output}
            )
            direction = "TOOL"
            key = (event.tool.name, event.arguments)
            if key in self._pending_tool_calls and self._pending_tool_calls[key]:
                tool_call_id = self._pending_tool_calls[key].pop(0)
            await self._logger.log_tool_call(
                tool_name=event.tool.name,
                args_json=_safe_json_loads(event.arguments),
                result_json=event.output
                if isinstance(event.output, dict)
                else {"output": str(event.output)},
                status="SUCCEEDED",
                error_message=None,
                tool_call_external_id=tool_call_id,
                arguments_raw=event.arguments,
                output_raw=json.dumps(event.output, default=str),
                agent_name=event.agent.name,
            )
        elif event.type == "history_added":
            item_id = event.item.item_id
            payload["item"] = event.item.model_dump()
            await self._logger.upsert_realtime_item(
                item_id=item_id,
                content=event.item.model_dump(),
            )
            if hasattr(event.item, "role") and event.item.role == "user":
                direction = "USER"
            elif hasattr(event.item, "role") and event.item.role == "assistant":
                direction = "AGENT"
        elif event.type == "history_updated":
            payload["history_count"] = len(event.history)
            for history_item in event.history:
                try:
                    await self._logger.upsert_realtime_item(
                        item_id=history_item.item_id,
                        content=history_item.model_dump(),
                    )
                except Exception:
                    _LOGGER.debug("Failed to upsert history_updated item.", exc_info=True)
        elif event.type in ("audio", "audio_end", "audio_interrupted"):
            item_id = event.item_id
        elif event.type == "agent_start":
            agent_name = event.agent.name
        elif event.type == "agent_end":
            agent_name = event.agent.name
        elif event.type == "handoff":
            agent_name = event.to_agent.name
            payload.update({"from_agent": event.from_agent.name, "to_agent": event.to_agent.name})
        elif event.type == "guardrail_tripped":
            payload.update({"message": event.message})
        elif event.type == "error":
            payload.update({"error": event.error})

        await self._logger.log_session_event(
            event_type=event.type,
            payload=payload,
            direction=direction,
            item_id=item_id,
            tool_call_id=tool_call_id,
            agent_name=agent_name,
        )

    @staticmethod
    def _extract_session_id(raw_event: Any) -> str | None:
        """Extracts realtime session id from raw model session events.

        Args:
            raw_event: Raw event object emitted by the realtime model client.

        Returns:
            Session id when present, otherwise ``None``.
        """
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

    def _capture_session_id_from_event(self, event: RealtimeSessionEvent) -> None:
        """Caches realtime session id when session-created/updated events arrive.

        Args:
            event: Realtime session event potentially containing session metadata.
        """
        if event.type != "raw_model_event":
            return
        raw = event.data
        if raw.type not in {"session.created", "session.updated"}:
            return

        session_id = self._extract_session_id(raw)
        if not session_id:
            return

        self._session_id = session_id
        if self._logger:
            self._logger.set_session_id(session_id)
