from __future__ import annotations

import asyncio
import base64

import pytest

import voice_gateway.app.engine.realtime_engine as realtime_engine_module
from voice_gateway.app.engine.providers.types import ProviderEvent, ProviderSessionInfo
from voice_gateway.app.engine.realtime_engine import RealtimeCallEngine


def run(coro):
    return asyncio.run(coro)


class _FakeProvider:
    def __init__(self) -> None:
        self.start_called = False
        self.closed = False
        self.sent_audio: list[bytes] = []
        self.played_marks: list[tuple[str, int, int, str]] = []
        self.call_context: tuple[str | None, object | None] | None = None
        self.events_to_emit: list[ProviderEvent] = []

    async def start(self) -> ProviderSessionInfo:
        self.start_called = True
        return ProviderSessionInfo(
            provider_name="openai",
            component="realtime",
            agent_name="Golf Voice Agent",
            model_name="gpt-4o-realtime-preview-2024-12-17",
            external_session_id="sess-start-1",
            metadata_json={"voice": "alloy"},
        )

    async def send_audio(self, audio_bytes: bytes) -> None:
        self.sent_audio.append(audio_bytes)

    async def events(self):
        for event in self.events_to_emit:
            yield event

    async def on_output_played(
        self,
        *,
        item_id: str,
        content_index: int,
        byte_count: int,
        mark_id: str,
    ) -> None:
        self.played_marks.append((item_id, content_index, byte_count, mark_id))

    def set_call_context(self, *, call_id: str | None, logger) -> None:  # noqa: ANN001
        self.call_context = (call_id, logger)

    async def close(self) -> None:
        self.closed = True


class _FakeDbLogger:
    def __init__(self, call_id: str) -> None:
        self.call_id = call_id
        self.ensure_call_args: dict[str, object] | None = None
        self.provider_sessions: list[dict[str, object]] = []
        self.call_events: list[str] = []

    async def ensure_call(self, **kwargs) -> None:  # noqa: ANN003, ANN001
        self.ensure_call_args = dict(kwargs)

    async def ensure_provider_session(self, **kwargs) -> str:  # noqa: ANN003, ANN001
        self.provider_sessions.append(dict(kwargs))
        return "11111111-1111-1111-1111-111111111111"

    def set_provider_session(self, **kwargs) -> None:  # noqa: ANN003, ANN001
        del kwargs

    async def log_call_event(self, *, event_name: str, **kwargs) -> None:  # noqa: ANN003, ANN001
        del kwargs
        self.call_events.append(event_name)

    async def log_session_event(self, **kwargs) -> None:  # noqa: ANN003, ANN001
        del kwargs

    async def upsert_conversation_item(self, **kwargs) -> None:  # noqa: ANN003, ANN001
        del kwargs

    async def log_tool_call(self, **kwargs) -> None:  # noqa: ANN003, ANN001
        del kwargs

    async def finalize_call(self) -> None:
        return None


def test_start_and_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_op_loop(self) -> None:
        del self
        return None

    provider = _FakeProvider()
    engine = RealtimeCallEngine(provider=provider)

    monkeypatch.setattr(RealtimeCallEngine, "_provider_event_loop", no_op_loop)
    monkeypatch.setattr(RealtimeCallEngine, "_buffer_flush_loop", no_op_loop)

    emitted: list[dict[str, object]] = []

    async def emit(payload: dict[str, object]) -> None:
        emitted.append(payload)

    run(engine.start(emit_twilio_message=emit))

    assert provider.start_called is True
    assert engine._provider_info is not None

    run(engine.shutdown())

    assert provider.closed is True
    assert emitted == []


def test_handle_twilio_message_stop_returns_false() -> None:
    engine = RealtimeCallEngine(provider=_FakeProvider())

    should_continue = run(engine.handle_twilio_message({"event": "stop"}))

    assert should_continue is False


def test_handle_media_message_flushes_audio_to_provider() -> None:
    provider = _FakeProvider()
    engine = RealtimeCallEngine(provider=provider)
    engine._buffer_size_bytes = 3
    engine._startup_audio_warmed = True

    payload = base64.b64encode(b"abcd").decode("utf-8")
    should_continue = run(
        engine.handle_twilio_message({"event": "media", "media": {"payload": payload}})
    )

    assert should_continue is True
    assert provider.sent_audio == [b"abcd"]
    assert engine._agent_input_audio_chunks == 1


def test_provider_audio_event_emits_media_and_mark_frames() -> None:
    engine = RealtimeCallEngine(provider=_FakeProvider())
    engine._stream_sid = "MZ-1"

    emitted: list[dict[str, object]] = []

    async def emit(payload: dict[str, object]) -> None:
        emitted.append(payload)

    engine._emit_twilio_message = emit

    event = ProviderEvent(
        event_name="audio_output",
        provider_name="openai",
        audio_bytes=b"\x00\x01",
        item_id="item-1",
        content_index=0,
    )

    run(engine._handle_provider_event(event))

    assert len(emitted) == 2
    assert emitted[0]["event"] == "media"
    assert emitted[1]["event"] == "mark"


def test_start_event_wires_logger_and_provider_context(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _FakeProvider()
    engine = RealtimeCallEngine(provider=provider)
    engine._provider_info = ProviderSessionInfo(
        provider_name="openai",
        component="realtime",
        agent_name="Golf Voice Agent",
        model_name="gpt-4o-realtime-preview-2024-12-17",
        external_session_id="sess-xyz",
        metadata_json={"voice": "alloy"},
    )

    monkeypatch.setattr(realtime_engine_module, "DbLogger", _FakeDbLogger)

    run(
        engine._handle_start_event(
            {
                "start": {
                    "streamSid": "MZ-1",
                    "callSid": "CA-1",
                    "customParameters": {"from": "+15550001", "to": "+15550002"},
                }
            }
        )
    )

    assert engine._stream_sid == "MZ-1"
    assert engine._call_id == "CA-1"
    assert isinstance(engine._logger, _FakeDbLogger)
    assert engine._logger.ensure_call_args is not None
    assert engine._logger.ensure_call_args["engine_mode"] == realtime_engine_module.settings.VOICE_EXECUTION_MODE
    assert engine._provider_session_id == "11111111-1111-1111-1111-111111111111"
    assert provider.call_context is not None
    assert provider.call_context[0] == "CA-1"
