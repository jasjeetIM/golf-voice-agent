from __future__ import annotations

from voice_gateway.app.twilio.twiml import build_connect_stream_twiml


def test_build_connect_stream_twiml_includes_custom_parameters() -> None:
    twiml = build_connect_stream_twiml(
        "wss://example.test/twilio/stream",
        from_number="+15550001111",
        to_number="+15550002222",
    )

    assert '<Parameter name="from" value="+15550001111" />' in twiml
    assert '<Parameter name="to" value="+15550002222" />' in twiml


def test_build_connect_stream_twiml_omits_empty_parameters() -> None:
    twiml = build_connect_stream_twiml("wss://example.test/twilio/stream")

    assert 'name="from"' not in twiml
    assert 'name="to"' not in twiml
