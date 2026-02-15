from __future__ import annotations

import asyncio
import json

from fastapi import WebSocketDisconnect
from starlette.websockets import WebSocketState

import voice_gateway.app.ws.twilio_handler as twilio_handler_module
from voice_gateway.app.ws.twilio_handler import TwilioHandler


def run(coro):
    return asyncio.run(coro)


class _FakeWebSocket:
    def __init__(self, incoming_messages: list[str] | None = None) -> None:
        self._incoming_messages = list(incoming_messages or [])
        self.sent_texts: list[str] = []
        self.accepted = False
        self.closed = False
        self.client_state = WebSocketState.CONNECTED

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, text: str) -> None:
        self.sent_texts.append(text)

    async def receive_text(self) -> str:
        if self._incoming_messages:
            return self._incoming_messages.pop(0)
        raise WebSocketDisconnect(code=1000)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        del code, reason
        self.closed = True
        self.client_state = WebSocketState.DISCONNECTED


class _FakeEngine:
    def __init__(self) -> None:
        self.started = False
        self.shutdown_calls = 0
        self.emit_callback = None
        self.messages: list[dict[str, object]] = []
        self.return_values: list[bool] = []

    async def start(self, *, emit_twilio_message):  # noqa: ANN001
        self.started = True
        self.emit_callback = emit_twilio_message

    async def handle_twilio_message(self, message: dict[str, object]) -> bool:
        self.messages.append(message)
        if self.return_values:
            return self.return_values.pop(0)
        return True

    async def shutdown(self) -> None:
        self.shutdown_calls += 1


def test_start_creates_engine_accepts_websocket_and_starts_loop(monkeypatch) -> None:
    async def no_op_loop(self) -> None:
        del self
        return None

    websocket = _FakeWebSocket()
    handler = TwilioHandler(websocket)  # type: ignore[arg-type]
    fake_engine = _FakeEngine()

    def fake_factory(*, mode):
        del mode
        return fake_engine

    monkeypatch.setattr(twilio_handler_module, "create_call_engine", fake_factory)
    monkeypatch.setattr(TwilioHandler, "_twilio_message_loop", no_op_loop)

    run(handler.start())

    assert websocket.accepted is True
    assert fake_engine.started is True
    assert handler._message_loop_task is not None

    run(handler.shutdown())


def test_wait_until_done_waits_message_loop_then_calls_shutdown() -> None:
    websocket = _FakeWebSocket()
    handler = TwilioHandler(websocket)  # type: ignore[arg-type]

    async def scenario() -> bool:
        shutdown_called = False

        async def fake_shutdown() -> None:
            nonlocal shutdown_called
            shutdown_called = True

        async def message_loop() -> None:
            await asyncio.sleep(0)

        handler.shutdown = fake_shutdown  # type: ignore[assignment]
        handler._message_loop_task = asyncio.create_task(message_loop())
        await handler.wait_until_done()
        return shutdown_called

    assert run(scenario()) is True


def test_shutdown_is_idempotent_and_closes_engine_and_websocket() -> None:
    websocket = _FakeWebSocket()
    handler = TwilioHandler(websocket)  # type: ignore[arg-type]
    handler._engine = _FakeEngine()  # type: ignore[assignment]

    run(handler.shutdown())
    run(handler.shutdown())

    assert websocket.closed is True
    assert handler._engine.shutdown_calls == 1


def test_message_loop_forwards_twilio_payloads_to_engine() -> None:
    websocket = _FakeWebSocket(
        incoming_messages=[
            json.dumps({"event": "start"}),
            json.dumps({"event": "stop"}),
        ]
    )
    handler = TwilioHandler(websocket)  # type: ignore[arg-type]
    fake_engine = _FakeEngine()
    fake_engine.return_values = [True, False]
    handler._engine = fake_engine  # type: ignore[assignment]

    run(handler._twilio_message_loop())

    assert [message["event"] for message in fake_engine.messages] == ["start", "stop"]


def test_message_loop_drops_invalid_json_and_continues() -> None:
    websocket = _FakeWebSocket(
        incoming_messages=[
            "not-json",
            json.dumps({"event": "start"}),
            json.dumps({"event": "stop"}),
        ]
    )
    handler = TwilioHandler(websocket)  # type: ignore[arg-type]
    fake_engine = _FakeEngine()
    fake_engine.return_values = [True, False]
    handler._engine = fake_engine  # type: ignore[assignment]

    run(handler._twilio_message_loop())

    assert [message["event"] for message in fake_engine.messages] == ["start", "stop"]


def test_emit_twilio_message_sends_json_and_updates_metrics() -> None:
    websocket = _FakeWebSocket()
    handler = TwilioHandler(websocket)  # type: ignore[arg-type]

    run(
        handler._emit_twilio_message(
            {
                "event": "media",
                "media": {"payload": "abcd"},
            }
        )
    )

    assert len(websocket.sent_texts) == 1
    assert handler._outbound_message_count == 1
    assert handler._outbound_media_frames == 1
    assert handler._outbound_media_bytes == 4
