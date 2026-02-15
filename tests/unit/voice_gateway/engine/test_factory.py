from __future__ import annotations

import pytest

from voice_gateway.app.engine.factory import create_call_engine, supported_engine_modes
from voice_gateway.app.engine.realtime_engine import RealtimeCallEngine


def test_create_call_engine_returns_realtime_engine() -> None:
    engine = create_call_engine(
        mode="realtime",
    )

    assert isinstance(engine, RealtimeCallEngine)


def test_create_call_engine_rejects_pipeline_until_implemented() -> None:
    with pytest.raises(NotImplementedError):
        create_call_engine(
            mode="pipeline",
        )


def test_create_call_engine_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        create_call_engine(
            mode="unknown",
        )


def test_supported_engine_modes_lists_realtime_and_pipeline() -> None:
    assert supported_engine_modes() == ("realtime", "pipeline")
