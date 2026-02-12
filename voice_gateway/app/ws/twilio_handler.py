from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any

from fastapi import WebSocket

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


class TwilioHandler:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.session: RealtimeSession | None = None
        self.playback_tracker = RealtimePlaybackTracker()
        self._message_loop_task: asyncio.Task[None] | None = None
        self._realtime_loop_task: asyncio.Task[None] | None = None
        self._buffer_flush_task: asyncio.Task[None] | None = None

        self.CHUNK_LENGTH_S = 0.05
        self.SAMPLE_RATE = 8000
        self.BUFFER_SIZE_BYTES = int(self.SAMPLE_RATE * self.CHUNK_LENGTH_S)

        self._stream_sid: str | None = None
        self._audio_buffer = bytearray()
        self._last_buffer_send_time = time.time()

        self._mark_counter = 0
        self._mark_data: dict[str, tuple[str, int, int]] = {}

        self._call_id: str | None = None
        self._logger: DbLogger | None = None
        self._backend_client: BackendClient | None = None
        self._mcp_server: BackendMCPServer | None = None

        self._pending_tool_calls: dict[tuple[str, str], list[str]] = {}

    async def start(self) -> None:
        self._backend_client = BackendClient(settings.backend_url, settings.BACKEND_API_KEY)
        self._mcp_server = BackendMCPServer(self._backend_client, logger=self._logger)
        agent = create_agent(self._mcp_server)

        runner = RealtimeRunner(agent)
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required")

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
        await self.websocket.accept()

        self._realtime_loop_task = asyncio.create_task(self._realtime_session_loop())
        self._message_loop_task = asyncio.create_task(self._twilio_message_loop())
        self._buffer_flush_task = asyncio.create_task(self._buffer_flush_loop())

    async def wait_until_done(self) -> None:
        if self._message_loop_task:
            await self._message_loop_task
        if self.session:
            await self.session.close()
        if self._backend_client:
            await self._backend_client.close()

    async def _realtime_session_loop(self) -> None:
        assert self.session is not None
        try:
            async for event in self.session:
                await self._handle_realtime_event(event)
        except Exception:
            pass

    async def _twilio_message_loop(self) -> None:
        try:
            while True:
                message_text = await self.websocket.receive_text()
                message = json.loads(message_text)
                await self._handle_twilio_message(message)
        except Exception:
            pass

    async def _handle_realtime_event(self, event: RealtimeSessionEvent) -> None:
        if self._logger:
            await self._log_session_event(event)

        if event.type == "audio":
            base64_audio = base64.b64encode(event.audio.data).decode("utf-8")
            if self._logger:
                await self._logger.log_call_event(
                    event_type="media",
                    payload={"bytes": len(event.audio.data), "item_id": event.audio.item_id},
                    direction="OUT",
                    source="OPENAI",
                )
            await self.websocket.send_text(
                json.dumps(
                    {
                        "event": "media",
                        "streamSid": self._stream_sid,
                        "media": {"payload": base64_audio},
                    }
                )
            )

            self._mark_counter += 1
            mark_id = str(self._mark_counter)
            self._mark_data[mark_id] = (
                event.audio.item_id,
                event.audio.content_index,
                len(event.audio.data),
            )

            await self.websocket.send_text(
                json.dumps(
                    {
                        "event": "mark",
                        "streamSid": self._stream_sid,
                        "mark": {"name": mark_id},
                    }
                )
            )
        elif event.type == "audio_interrupted":
            if self._logger:
                await self._logger.log_call_event(
                    event_type="clear",
                    payload={"item_id": event.item_id},
                    direction="OUT",
                    source="OPENAI",
                )
            await self.websocket.send_text(
                json.dumps({"event": "clear", "streamSid": self._stream_sid})
            )
        else:
            pass

    async def _handle_twilio_message(self, message: dict[str, Any]) -> None:
        event = message.get("event")
        if event == "start":
            start_data = message.get("start", {})
            self._stream_sid = start_data.get("streamSid")
            call_sid = start_data.get("callSid")
            if call_sid:
                self._call_id = call_sid
                self._logger = DbLogger(call_sid, session_id=None)
                if self._mcp_server:
                    self._mcp_server.set_logger(self._logger)
                await self._logger.ensure_call(
                    from_number=start_data.get("customParameters", {}).get("from", ""),
                    to_number=start_data.get("customParameters", {}).get("to", ""),
                )
            if self._logger:
                await self._logger.log_call_event(
                    event_type=event or "unknown",
                    payload=message,
                    direction="IN",
                    source="TWILIO",
                )
        elif event == "media":
            if self._logger:
                await self._logger.log_call_event(
                    event_type=event or "unknown",
                    payload=message,
                    direction="IN",
                    source="TWILIO",
                )
            await self._handle_media_event(message)
        elif event == "mark":
            if self._logger:
                await self._logger.log_call_event(
                    event_type=event or "unknown",
                    payload=message,
                    direction="IN",
                    source="TWILIO",
                )
            await self._handle_mark_event(message)
        elif event == "stop":
            if self._logger:
                await self._logger.log_call_event(
                    event_type=event or "unknown",
                    payload=message,
                    direction="IN",
                    source="TWILIO",
                )
            if self.session:
                await self.session.close()
        else:
            if self._logger:
                await self._logger.log_call_event(
                    event_type=event or "unknown",
                    payload=message,
                    direction="IN",
                    source="TWILIO",
                )

    async def _handle_media_event(self, message: dict[str, Any]) -> None:
        media = message.get("media", {})
        payload = media.get("payload", "")
        if not payload or not self.session:
            return

        ulaw_bytes = base64.b64decode(payload)
        self._audio_buffer.extend(ulaw_bytes)

        if len(self._audio_buffer) >= self.BUFFER_SIZE_BYTES:
            await self._flush_audio_buffer()

    async def _handle_mark_event(self, message: dict[str, Any]) -> None:
        mark_data = message.get("mark", {})
        mark_id = mark_data.get("name", "")
        if mark_id in self._mark_data:
            item_id, item_content_index, byte_count = self._mark_data[mark_id]
            audio_bytes = b"\x00" * byte_count
            self.playback_tracker.on_play_bytes(item_id, item_content_index, audio_bytes)
            del self._mark_data[mark_id]

    async def _flush_audio_buffer(self) -> None:
        if not self._audio_buffer or not self.session:
            return
        buffer_data = bytes(self._audio_buffer)
        self._audio_buffer.clear()
        self._last_buffer_send_time = time.time()
        await self.session.send_audio(buffer_data)

    async def _buffer_flush_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.CHUNK_LENGTH_S)
                current_time = time.time()
                if self._audio_buffer and current_time - self._last_buffer_send_time > self.CHUNK_LENGTH_S * 2:
                    await self._flush_audio_buffer()
        except Exception:
            pass

    async def _log_session_event(self, event: RealtimeSessionEvent) -> None:
        if not self._logger:
            return

        def _safe_json_loads(data: str | None) -> dict[str, Any]:
            if not data:
                return {}
            try:
                return json.loads(data)
            except Exception:
                return {}

        payload: dict[str, Any] = {"type": event.type}
        item_id: str | None = None
        tool_call_id: str | None = None
        agent_name: str | None = None
        direction = "SYSTEM"

        if event.type == "raw_model_event":
            raw = event.data
            payload["raw_type"] = raw.type
            if isinstance(raw, RealtimeModelToolCallEvent):
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
            item_id = getattr(raw, "item_id", None)
            if raw.type == "item_updated" and hasattr(raw, "item"):
                try:
                    await self._logger.upsert_realtime_item(
                        item_id=raw.item.item_id,
                        content=raw.item.model_dump(),
                    )
                except Exception:
                    pass
        elif event.type == "tool_start":
            payload.update({"tool": event.tool.name, "arguments": event.arguments})
            direction = "TOOL"
        elif event.type == "tool_end":
            payload.update({"tool": event.tool.name, "arguments": event.arguments, "output": event.output})
            direction = "TOOL"
            key = (event.tool.name, event.arguments)
            if key in self._pending_tool_calls and self._pending_tool_calls[key]:
                tool_call_id = self._pending_tool_calls[key].pop(0)
            await self._logger.log_tool_call(
                tool_name=event.tool.name,
                args_json=_safe_json_loads(event.arguments),
                result_json=event.output if isinstance(event.output, dict) else {"output": str(event.output)},
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
            for item in event.history:
                try:
                    await self._logger.upsert_realtime_item(
                        item_id=item.item_id,
                        content=item.model_dump(),
                    )
                except Exception:
                    pass
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
