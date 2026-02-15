from __future__ import annotations

import asyncio

import pytest
from mcp import McpError

from voice_gateway.app.mcp.backend_server import BackendMCPServer


class _FakeBackendClient:
    def __init__(self) -> None:
        self.search_payloads: list[dict[str, object]] = []
        self.closed = False

    async def search_tee_times(self, payload: dict[str, object]) -> dict[str, object]:
        self.search_payloads.append(payload)
        return {"ok": True}

    async def book_tee_time(self, payload: dict[str, object]) -> dict[str, object]:
        return payload

    async def modify_reservation(self, payload: dict[str, object]) -> dict[str, object]:
        return payload

    async def cancel_reservation(self, payload: dict[str, object]) -> dict[str, object]:
        return payload

    async def send_sms_confirmation(self, payload: dict[str, object]) -> dict[str, object]:
        return payload

    async def get_reservation_details(self, payload: dict[str, object]) -> dict[str, object]:
        return payload

    async def quote_reservation_change(self, payload: dict[str, object]) -> dict[str, object]:
        return payload

    async def check_slot_capacity(self, payload: dict[str, object]) -> dict[str, object]:
        return payload

    async def close(self) -> None:
        self.closed = True


class _FakeLogger:
    def __init__(self) -> None:
        self.call_id = "CA1"
        self.calls: list[dict[str, object]] = []
        self.resolved_tool_call_id: str | None = None
        self.resolved_tool_call_external_id: str | None = None

    async def resolve_tool_call_reference(
        self, *, tool_name: str, args_json: dict[str, object]
    ) -> tuple[str | None, str | None]:
        del tool_name, args_json
        return self.resolved_tool_call_id, self.resolved_tool_call_external_id

    async def log_mcp_call(self, **kwargs: object) -> None:
        self.calls.append(dict(kwargs))


def run(coro):
    return asyncio.run(coro)


def test_call_tool_injects_call_id_when_missing() -> None:
    client = _FakeBackendClient()
    server = BackendMCPServer(client)  # type: ignore[arg-type]
    server.set_call_id("CA123")

    run(
        server.call_tool(
            "search_tee_times",
            {"players": 2},
        )
    )

    assert client.search_payloads == [{"players": 2, "call_id": "CA123"}]


def test_call_tool_preserves_existing_call_id() -> None:
    client = _FakeBackendClient()
    server = BackendMCPServer(client)  # type: ignore[arg-type]
    server.set_call_id("CA123")

    run(
        server.call_tool(
            "search_tee_times",
            {"players": 2, "call_id": "CA999"},
        )
    )

    assert client.search_payloads == [{"players": 2, "call_id": "CA999"}]


def test_get_prompt_raises_mcp_error_for_unknown_prompt() -> None:
    client = _FakeBackendClient()
    server = BackendMCPServer(client)  # type: ignore[arg-type]

    with pytest.raises(McpError):
        run(server.get_prompt("unknown"))


def test_list_tools_returns_expected_catalog() -> None:
    client = _FakeBackendClient()
    server = BackendMCPServer(client)  # type: ignore[arg-type]

    tools = run(server.list_tools())

    assert len(tools) == 8
    assert [tool.name for tool in tools] == [
        "search_tee_times",
        "book_tee_time",
        "modify_reservation",
        "cancel_reservation",
        "send_sms_confirmation",
        "get_reservation_details",
        "quote_reservation_change",
        "check_slot_capacity",
    ]


def test_call_tool_unknown_name_returns_error_payload() -> None:
    client = _FakeBackendClient()
    server = BackendMCPServer(client)  # type: ignore[arg-type]

    result = run(server.call_tool("unknown_tool", {"foo": "bar"}))

    assert "error" in result.structuredContent
    assert "Unknown tool: unknown_tool" in str(result.structuredContent["error"])


def test_call_tool_logs_mcp_call_when_logger_is_attached() -> None:
    client = _FakeBackendClient()
    logger = _FakeLogger()
    logger.resolved_tool_call_id = "11111111-1111-1111-1111-111111111111"
    logger.resolved_tool_call_external_id = "call_ext_123"
    server = BackendMCPServer(client, logger=logger)  # type: ignore[arg-type]
    server.set_call_id("CA777")

    run(server.call_tool("search_tee_times", {}))

    assert len(logger.calls) == 1
    assert logger.calls[0]["server_name"] == "backend_tools"
    assert logger.calls[0]["tool_name"] == "search_tee_times"
    assert logger.calls[0]["tool_call_id"] == "11111111-1111-1111-1111-111111111111"
    assert logger.calls[0]["tool_call_external_id"] == "call_ext_123"
    assert isinstance(logger.calls[0]["latency_ms"], int)
    request_json = logger.calls[0]["request_json"]
    assert isinstance(request_json, dict)
    assert request_json["arguments"]["call_id"] == "CA777"


def test_list_tools_search_schema_has_no_course_id() -> None:
    client = _FakeBackendClient()
    server = BackendMCPServer(client)  # type: ignore[arg-type]

    tools = run(server.list_tools())
    search_tool = next(tool for tool in tools if tool.name == "search_tee_times")
    properties = search_tool.inputSchema.get("properties", {})

    assert "course_id" not in properties


def test_cleanup_closes_backend_client() -> None:
    client = _FakeBackendClient()
    server = BackendMCPServer(client)  # type: ignore[arg-type]

    run(server.cleanup())

    assert client.closed is True
