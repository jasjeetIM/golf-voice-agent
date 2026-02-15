"""Twilio websocket transport bridge.

`TwilioHandler` is intentionally transport-only:
- It accepts/reads/writes the Twilio websocket.
- It forwards inbound Twilio JSON payloads to the configured call engine.
- It sends outbound engine payloads back to Twilio.

All provider-specific call logic (audio buffering, realtime session handling,
tool/event logging, and observability writes) lives in the engine layer.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ..config import settings
from ..engine.base import CallEngine
from ..engine.factory import create_call_engine

_LOGGER = logging.getLogger(__name__)


class TwilioHandler:
    """Owns websocket transport lifecycle for one Twilio media stream."""

    def __init__(self, websocket: WebSocket):
        """Initializes websocket transport state.

        Args:
            websocket: Active Twilio websocket connection.
        """
        self.websocket = websocket
        self._engine: CallEngine | None = None
        self._message_loop_task: asyncio.Task[None] | None = None
        self._is_shutting_down = False

        # Minimal transport diagnostics.
        self._inbound_message_count = 0
        self._outbound_message_count = 0
        self._inbound_media_frames = 0
        self._inbound_media_bytes = 0
        self._outbound_media_frames = 0
        self._outbound_media_bytes = 0

    async def start(self) -> None:
        """Starts engine resources and begins Twilio transport message loop."""
        self._engine = create_call_engine(mode=settings.VOICE_EXECUTION_MODE)

        # Start engine before accepting Twilio frames so inbound media can be
        # consumed immediately after websocket accept.
        await self._engine.start(emit_twilio_message=self._emit_twilio_message)
        await self.websocket.accept()
        self._message_loop_task = asyncio.create_task(self._twilio_message_loop())
        _LOGGER.debug("TwilioHandler started.")

    async def wait_until_done(self) -> None:
        """Waits until the Twilio receive loop exits, then shuts down."""
        if not self._message_loop_task:
            return
        try:
            await self._message_loop_task
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Idempotently shuts down transport and engine resources."""
        if self._is_shutting_down:
            return
        self._is_shutting_down = True

        current = asyncio.current_task()
        if self._message_loop_task and self._message_loop_task is not current:
            if not self._message_loop_task.done():
                self._message_loop_task.cancel()
            try:
                await self._message_loop_task
            except (asyncio.CancelledError, Exception):
                pass

        if self._engine:
            try:
                await self._engine.shutdown()
            except Exception:
                _LOGGER.exception("Engine shutdown failed.")

        if self.websocket.client_state != WebSocketState.DISCONNECTED:
            try:
                await self.websocket.close()
            except Exception:
                _LOGGER.debug("Websocket close failed during shutdown.", exc_info=True)

        self._log_transport_summary()

    async def _twilio_message_loop(self) -> None:
        """Reads Twilio websocket messages and forwards them to the engine."""
        assert self._engine is not None
        try:
            while not self._is_shutting_down:
                message_text = await self.websocket.receive_text()
                self._inbound_message_count += 1

                try:
                    message = json.loads(message_text)
                except json.JSONDecodeError:
                    _LOGGER.warning("Received non-JSON Twilio frame; dropping.")
                    continue

                self._update_inbound_metrics(message)
                should_continue = await self._engine.handle_twilio_message(message)
                if not should_continue:
                    break
        except asyncio.CancelledError:
            raise
        except WebSocketDisconnect:
            _LOGGER.info("Twilio websocket disconnected.")
        except Exception:
            _LOGGER.exception("Twilio message loop failed.")

    async def _emit_twilio_message(self, payload: dict[str, Any]) -> None:
        """Sends one engine-produced payload to the Twilio websocket."""
        self._outbound_message_count += 1
        self._update_outbound_metrics(payload)

        try:
            await self.websocket.send_text(json.dumps(payload))
        except Exception:
            _LOGGER.exception("Failed sending outbound Twilio frame.")
            raise

    def _update_inbound_metrics(self, message: dict[str, Any]) -> None:
        """Updates transport counters for inbound Twilio frames."""
        if message.get("event") != "media":
            return

        media = message.get("media", {})
        payload = media.get("payload")
        if not isinstance(payload, str):
            return

        self._inbound_media_frames += 1
        self._inbound_media_bytes += len(payload)

    def _update_outbound_metrics(self, payload: dict[str, Any]) -> None:
        """Updates transport counters for outbound Twilio frames."""
        if payload.get("event") != "media":
            return

        media = payload.get("media", {})
        audio_payload = media.get("payload")
        if not isinstance(audio_payload, str):
            return

        self._outbound_media_frames += 1
        self._outbound_media_bytes += len(audio_payload)

    def _log_transport_summary(self) -> None:
        """Logs a compact transport-level message summary for one call."""
        _LOGGER.debug(
            "Twilio transport summary inbound_messages=%d outbound_messages=%d "
            "inbound_media_frames=%d inbound_media_payload_chars=%d "
            "outbound_media_frames=%d outbound_media_payload_chars=%d",
            self._inbound_message_count,
            self._outbound_message_count,
            self._inbound_media_frames,
            self._inbound_media_bytes,
            self._outbound_media_frames,
            self._outbound_media_bytes,
        )
