from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace

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
        self.close_code: int | None = None
        self.close_reason: str | None = None
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
        self.closed = True
        self.close_code = code
        self.close_reason = reason
        self.client_state = WebSocketState.DISCONNECTED


class _FakeSession:
    def __init__(self) -> None:
        self.entered = False
        self.closed = False
        self.sent_audio: list[bytes] = []
        self.events: list[object] = []

    async def enter(self) -> None:
        self.entered = True

    async def close(self) -> None:
        self.closed = True

    async def send_audio(self, audio: bytes) -> None:
        self.sent_audio.append(audio)

    async def _iter_events(self):
        for event in self.events:
            yield event

    def __aiter__(self):
        return self._iter_events()


class _FakeBackendClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakeBackendMCPServer:
    def __init__(self, client: _FakeBackendClient, logger=None) -> None:
        self.client = client
        self.logger = logger
        self.call_ids: list[str] = []

    def set_logger(self, logger) -> None:
        self.logger = logger

    def set_call_id(self, call_id: str | None) -> None:
        if call_id:
            self.call_ids.append(call_id)


class _FakeRunner:
    last_model_config: dict[str, object] | None = None
    last_agent: object | None = None

    def __init__(self, agent: object) -> None:
        self.agent = agent

    async def run(self, model_config: dict[str, object]) -> _FakeSession:
        _FakeRunner.last_model_config = model_config
        _FakeRunner.last_agent = self.agent
        return _FakeSession()


class _FakeDbLogger:
    def __init__(self, call_id: str, session_id: str | None = None) -> None:
        self.call_id = call_id
        self.session_id = session_id
        self.ensure_call_calls: list[tuple[str, str]] = []
        self.call_event_calls: list[dict[str, object]] = []
        self.session_event_calls: list[dict[str, object]] = []
        self.tool_call_calls: list[dict[str, object]] = []
        self.item_upsert_calls: list[dict[str, object]] = []

    def set_session_id(self, session_id: str | None) -> None:
        self.session_id = session_id

    async def ensure_call(self, from_number: str, to_number: str) -> None:
        self.ensure_call_calls.append((from_number, to_number))

    async def log_call_event(self, **kwargs: object) -> None:
        self.call_event_calls.append(dict(kwargs))

    async def log_session_event(self, **kwargs: object) -> None:
        self.session_event_calls.append(dict(kwargs))

    async def log_tool_call(self, **kwargs: object) -> None:
        self.tool_call_calls.append(dict(kwargs))

    async def upsert_realtime_item(self, **kwargs: object) -> None:
        self.item_upsert_calls.append(dict(kwargs))


def test_start_initializes_realtime_session_and_background_tasks(monkeypatch) -> None:
    async def no_op_loop(self) -> None:
        del self
        return None

    websocket = _FakeWebSocket()
    handler = TwilioHandler(websocket)  # type: ignore[arg-type]

    monkeypatch.setattr(twilio_handler_module, "BackendClient", _FakeBackendClient)
    monkeypatch.setattr(twilio_handler_module, "BackendMCPServer", _FakeBackendMCPServer)
    monkeypatch.setattr(twilio_handler_module, "create_agent", lambda server: {"server": server})
    monkeypatch.setattr(twilio_handler_module, "RealtimeRunner", _FakeRunner)
    monkeypatch.setattr(TwilioHandler, "_realtime_session_loop", no_op_loop)
    monkeypatch.setattr(TwilioHandler, "_twilio_message_loop", no_op_loop)
    monkeypatch.setattr(TwilioHandler, "_buffer_flush_loop", no_op_loop)
    monkeypatch.setattr(twilio_handler_module.settings, "OPENAI_API_KEY", "test-key")

    run(handler.start())

    assert websocket.accepted is True
    assert isinstance(handler.session, _FakeSession)
    assert handler.session.entered is True
    assert handler._message_loop_task is not None
    assert handler._realtime_loop_task is not None
    assert handler._buffer_flush_task is not None
    assert _FakeRunner.last_model_config is not None

    run(handler.shutdown())


def test_wait_until_done_waits_for_message_loop_then_shuts_down() -> None:
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


def test_shutdown_closes_resources_and_is_idempotent() -> None:
    websocket = _FakeWebSocket()
    handler = TwilioHandler(websocket)  # type: ignore[arg-type]
    handler.session = _FakeSession()  # type: ignore[assignment]
    handler._backend_client = _FakeBackendClient("http://backend", "key")  # type: ignore[assignment]

    async def sleeper() -> None:
        await asyncio.sleep(30)

    async def scenario() -> None:
        handler._message_loop_task = asyncio.create_task(sleeper())
        handler._realtime_loop_task = asyncio.create_task(sleeper())
        handler._buffer_flush_task = asyncio.create_task(sleeper())
        await handler.shutdown()
        await handler.shutdown()

    run(scenario())

    assert handler._is_shutting_down is True
    assert handler.session.closed is True
    assert handler._backend_client.closed is True
    assert websocket.closed is True


def test_handle_start_event_sets_logger_and_mcp_context(monkeypatch) -> None:
    websocket = _FakeWebSocket()
    handler = TwilioHandler(websocket)  # type: ignore[arg-type]
    handler._mcp_server = _FakeBackendMCPServer(_FakeBackendClient("http://backend", "key"))  # type: ignore[assignment]

    monkeypatch.setattr(twilio_handler_module, "DbLogger", _FakeDbLogger)

    message = {
        "start": {
            "streamSid": "MZ-1",
            "callSid": "CA-1",
            "customParameters": {"from": "+15550001", "to": "+15550002"},
        }
    }
    run(handler._handle_start_event(message))

    assert handler._stream_sid == "MZ-1"
    assert handler._call_id == "CA-1"
    assert isinstance(handler._logger, _FakeDbLogger)
    assert handler._logger.ensure_call_calls == [("+15550001", "+15550002")]
    assert handler._mcp_server.call_ids == ["CA-1"]


def test_handle_media_event_invalid_payload_is_ignored_and_logged() -> None:
    websocket = _FakeWebSocket()
    handler = TwilioHandler(websocket)  # type: ignore[arg-type]
    handler.session = _FakeSession()  # type: ignore[assignment]
    handler._logger = _FakeDbLogger("CA-1")  # type: ignore[assignment]

    run(handler._handle_media_event({"media": {"payload": "%%%notbase64%%%"}}))

    assert handler._audio_buffer == bytearray()
    event_types = [event["event_type"] for event in handler._logger.call_event_calls]
    assert "gateway_error" in event_types


def test_handle_media_event_flushes_buffer_to_realtime_session() -> None:
    websocket = _FakeWebSocket()
    handler = TwilioHandler(websocket)  # type: ignore[arg-type]
    session = _FakeSession()
    handler.session = session  # type: ignore[assignment]
    handler.BUFFER_SIZE_BYTES = 3

    payload = base64.b64encode(b"abcd").decode("utf-8")
    run(handler._handle_media_event({"media": {"payload": payload}}))

    assert session.sent_audio == [b"abcd"]
    assert handler._audio_buffer == bytearray()


def test_handle_realtime_audio_without_stream_sid_is_dropped() -> None:
    websocket = _FakeWebSocket()
    handler = TwilioHandler(websocket)  # type: ignore[arg-type]

    event = SimpleNamespace(
        type="audio",
        item_id="item-1",
        audio=SimpleNamespace(data=b"\x00\x01", item_id="item-1", content_index=0),
    )
    run(handler._handle_realtime_event(event))

    assert websocket.sent_texts == []


def test_handle_realtime_audio_sends_media_and_mark() -> None:
    websocket = _FakeWebSocket()
    handler = TwilioHandler(websocket)  # type: ignore[arg-type]
    handler._stream_sid = "MZ-1"
    handler._logger = _FakeDbLogger("CA-1")  # type: ignore[assignment]

    event = SimpleNamespace(
        type="audio",
        item_id="item-1",
        audio=SimpleNamespace(data=b"\x00\x01", item_id="item-1", content_index=0),
    )
    run(handler._handle_realtime_event(event))

    assert len(websocket.sent_texts) == 2
    outbound_media = json.loads(websocket.sent_texts[0])
    outbound_mark = json.loads(websocket.sent_texts[1])
    assert outbound_media["event"] == "media"
    assert outbound_mark["event"] == "mark"


def test_handle_twilio_message_routes_to_expected_handlers() -> None:
    websocket = _FakeWebSocket()
    handler = TwilioHandler(websocket)  # type: ignore[arg-type]
    calls: list[str] = []

    async def fake_start(_message: dict[str, object]) -> None:
        calls.append("start")

    async def fake_media(_message: dict[str, object]) -> None:
        calls.append("media")

    async def fake_mark(_message: dict[str, object]) -> None:
        calls.append("mark")

    async def fake_shutdown() -> None:
        calls.append("stop")

    handler._handle_start_event = fake_start  # type: ignore[assignment]
    handler._handle_media_event = fake_media  # type: ignore[assignment]
    handler._handle_mark_event = fake_mark  # type: ignore[assignment]
    handler.shutdown = fake_shutdown  # type: ignore[assignment]

    run(handler._handle_twilio_message({"event": "start"}))
    run(handler._handle_twilio_message({"event": "media"}))
    run(handler._handle_twilio_message({"event": "mark"}))
    run(handler._handle_twilio_message({"event": "stop"}))

    assert calls == ["start", "media", "mark", "stop"]


def test_capture_session_id_updates_handler_and_logger() -> None:
    websocket = _FakeWebSocket()
    handler = TwilioHandler(websocket)  # type: ignore[arg-type]
    logger = _FakeDbLogger("CA-1")
    handler._logger = logger  # type: ignore[assignment]

    event = SimpleNamespace(
        type="raw_model_event",
        data=SimpleNamespace(type="session.created", session={"id": "sess-1"}),
    )

    handler._capture_session_id_from_event(event)

    assert handler._session_id == "sess-1"
    assert logger.session_id == "sess-1"


def test_log_session_event_error_payload_is_written() -> None:
    websocket = _FakeWebSocket()
    handler = TwilioHandler(websocket)  # type: ignore[arg-type]
    logger = _FakeDbLogger("CA-1")
    handler._logger = logger  # type: ignore[assignment]

    event = SimpleNamespace(type="error", error={"message": "boom"})
    run(handler._log_session_event(event))

    assert len(logger.session_event_calls) == 1
    payload = logger.session_event_calls[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["error"] == {"message": "boom"}
