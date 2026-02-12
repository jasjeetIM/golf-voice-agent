from __future__ import annotations

from typing import Any

from .db import get_conn


class DbLogger:
    def __init__(self, call_id: str, session_id: str | None = None) -> None:
        self.call_id = call_id
        self.session_id = session_id

    async def ensure_call(self, from_number: str, to_number: str) -> None:
        try:
            async with get_conn() as conn:
                await conn.execute(
                    """
                    INSERT INTO calls (call_id, from_number, to_number, started_at, final_outcome)
                    VALUES ($1, $2, $3, now(), 'NO_ACTION')
                    ON CONFLICT (call_id) DO NOTHING
                    """,
                    self.call_id,
                    from_number,
                    to_number,
                )
        except Exception:
            pass

    async def log_call_event(
        self,
        *,
        event_type: str,
        payload: dict[str, Any] | None = None,
        direction: str | None = None,
        source: str | None = None,
    ) -> None:
        try:
            async with get_conn() as conn:
                await conn.execute(
                    """
                    INSERT INTO call_events (call_id, event_type, direction, source, payload_json)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    self.call_id,
                    event_type,
                    direction,
                    source,
                    payload or {},
                )
        except Exception:
            pass

    async def log_session_event(
        self,
        *,
        event_type: str,
        payload: dict[str, Any] | None = None,
        direction: str | None = None,
        item_id: str | None = None,
        tool_call_id: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        try:
            async with get_conn() as conn:
                await conn.execute(
                    """
                    INSERT INTO session_events
                    (call_id, session_id, agent_name, event_type, direction, item_id, tool_call_id, payload_json)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    """,
                    self.call_id,
                    self.session_id,
                    agent_name,
                    event_type,
                    direction,
                    item_id,
                    tool_call_id,
                    payload or {},
                )
        except Exception:
            pass

    async def upsert_realtime_item(
        self,
        *,
        item_id: str,
        content: dict[str, Any],
        event_id: str | None = None,
    ) -> None:
        try:
            async with get_conn() as conn:
                await conn.execute(
                    """
                    INSERT INTO realtime_items
                    (item_id, previous_item_id, call_id, session_id, role, type, status, content_json,
                     tool_call_id, tool_name, created_from_event_id, last_event_id, updated_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12, now())
                    ON CONFLICT (item_id) DO UPDATE
                    SET previous_item_id = EXCLUDED.previous_item_id,
                        role = EXCLUDED.role,
                        type = EXCLUDED.type,
                        status = EXCLUDED.status,
                        content_json = EXCLUDED.content_json,
                        tool_call_id = EXCLUDED.tool_call_id,
                        tool_name = EXCLUDED.tool_name,
                        last_event_id = EXCLUDED.last_event_id,
                        updated_at = now()
                    """,
                    item_id,
                    content.get("previous_item_id"),
                    self.call_id,
                    self.session_id,
                    content.get("role"),
                    content.get("type"),
                    content.get("status"),
                    content,
                    content.get("call_id"),
                    content.get("name"),
                    event_id,
                    event_id,
                )
        except Exception:
            pass

    async def log_tool_call(
        self,
        *,
        tool_name: str,
        args_json: dict[str, Any],
        result_json: dict[str, Any] | None,
        status: str,
        error_message: str | None,
        tool_call_external_id: str | None = None,
        tool_item_id: str | None = None,
        realtime_status: str | None = None,
        arguments_raw: str | None = None,
        output_raw: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        try:
            async with get_conn() as conn:
                await conn.execute(
                    """
                    INSERT INTO tool_calls
                    (call_id, session_id, tool_name, args_json, result_json, status, error_message,
                     tool_call_external_id, tool_item_id, realtime_status, arguments_raw, output_raw, agent_name)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                    """,
                    self.call_id,
                    self.session_id,
                    tool_name,
                    args_json,
                    result_json,
                    status,
                    error_message,
                    tool_call_external_id,
                    tool_item_id,
                    realtime_status,
                    arguments_raw,
                    output_raw,
                    agent_name,
                )
        except Exception:
            pass

    async def log_mcp_call(
        self,
        *,
        tool_call_id: str | None,
        tool_call_external_id: str | None = None,
        server_name: str,
        method: str,
        request_json: dict[str, Any] | None,
        response_json: dict[str, Any] | None,
        error_message: str | None,
    ) -> None:
        try:
            async with get_conn() as conn:
                await conn.execute(
                    """
                    INSERT INTO mcp_calls
                    (tool_call_id, tool_call_external_id, call_id, session_id, server_name, method, request_json, response_json, error_message)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    """,
                    tool_call_id,
                    tool_call_external_id,
                    self.call_id,
                    self.session_id,
                    server_name,
                    method,
                    request_json or {},
                    response_json or {},
                    error_message,
                )
        except Exception:
            pass
