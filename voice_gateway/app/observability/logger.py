"""Best-effort database logger for voice gateway observability events."""

from __future__ import annotations

import json
import logging
from typing import Any

from .db import get_conn

_LOGGER = logging.getLogger(__name__)


def _to_jsonb(value: Any) -> str:
    """Serializes a Python value for JSONB SQL parameters."""
    return json.dumps(value, default=str)


def _to_jsonb_or_none(value: Any | None) -> str | None:
    """Serializes optional Python values for nullable JSONB SQL parameters."""
    if value is None:
        return None
    return _to_jsonb(value)


class DbLogger:
    """Writes call/session/tool telemetry to Postgres without breaking call flow.

    Logging failures are intentionally non-fatal because observability should not
    interrupt an active phone call.
    """

    def __init__(self, call_id: str, session_id: str | None = None) -> None:
        self.call_id = call_id
        self.session_id = session_id
        _LOGGER.debug(
            "DbLogger initialized.",
            extra={"call_id": call_id, "session_id": session_id},
        )

    def set_session_id(self, session_id: str | None) -> None:
        """Updates the OpenAI realtime session id bound to future events."""
        self.session_id = session_id
        _LOGGER.debug(
            "DbLogger session_id updated.",
            extra={"call_id": self.call_id, "session_id": session_id},
        )

    async def ensure_call(self, from_number: str, to_number: str) -> None:
        """Creates the call row if it does not already exist."""
        await self._execute(
            operation_name="ensure_call",
            query="""
                INSERT INTO calls (call_id, from_number, to_number, started_at, final_outcome)
                VALUES ($1, $2, $3, now(), 'NO_ACTION')
                ON CONFLICT (call_id) DO NOTHING
            """,
            args=(self.call_id, from_number, to_number),
        )

    async def log_call_event(
        self,
        *,
        event_type: str,
        payload: dict[str, Any] | None = None,
        direction: str | None = None,
        source: str | None = None,
    ) -> None:
        """Persists a low-level call event (for example: Twilio media/marks)."""
        await self._execute(
            operation_name="log_call_event",
            query="""
                INSERT INTO call_events (call_id, event_type, direction, source, payload_json)
                VALUES ($1, $2, $3, $4, $5)
            """,
            args=(self.call_id, event_type, direction, source, _to_jsonb(payload or {})),
        )

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
        """Persists a normalized realtime session event."""
        await self._execute(
            operation_name="log_session_event",
            query="""
                INSERT INTO session_events
                (call_id, session_id, agent_name, event_type, direction, item_id, tool_call_id, payload_json)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            """,
            args=(
                self.call_id,
                self.session_id,
                agent_name,
                event_type,
                direction,
                item_id,
                tool_call_id,
                _to_jsonb(payload or {}),
            ),
        )

    async def upsert_realtime_item(
        self,
        *,
        item_id: str,
        content: dict[str, Any],
        event_id: str | None = None,
    ) -> None:
        """Upserts a realtime conversation item snapshot."""
        await self._execute(
            operation_name="upsert_realtime_item",
            query="""
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
            args=(
                item_id,
                content.get("previous_item_id"),
                self.call_id,
                self.session_id,
                content.get("role"),
                content.get("type"),
                content.get("status"),
                _to_jsonb(content),
                content.get("call_id"),
                content.get("name"),
                event_id,
                event_id,
            ),
        )

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
        """Persists a tool call lifecycle record."""
        await self._execute(
            operation_name="log_tool_call",
            query="""
                INSERT INTO tool_calls
                (call_id, session_id, tool_name, args_json, result_json, status, error_message,
                 tool_call_external_id, tool_item_id, realtime_status, arguments_raw, output_raw, agent_name)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            """,
            args=(
                self.call_id,
                self.session_id,
                tool_name,
                _to_jsonb(args_json),
                _to_jsonb_or_none(result_json),
                status,
                error_message,
                tool_call_external_id,
                tool_item_id,
                realtime_status,
                arguments_raw,
                output_raw,
                agent_name,
            ),
        )

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
        """Persists an MCP bridge call (request/response/error metadata)."""
        await self._execute(
            operation_name="log_mcp_call",
            query="""
                INSERT INTO mcp_calls
                (tool_call_id, tool_call_external_id, call_id, session_id, server_name, method, request_json, response_json, error_message)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            """,
            args=(
                tool_call_id,
                tool_call_external_id,
                self.call_id,
                self.session_id,
                server_name,
                method,
                _to_jsonb(request_json or {}),
                _to_jsonb(response_json or {}),
                error_message,
            ),
        )

    async def _execute(self, operation_name: str, query: str, args: tuple[Any, ...]) -> None:
        """Runs a single SQL write and logs failures without raising."""
        _LOGGER.debug(
            "Executing observability DB write.",
            extra={
                "operation": operation_name,
                "call_id": self.call_id,
                "arg_count": len(args),
            },
        )
        try:
            async with get_conn() as conn:
                await conn.execute(query, *args)
            _LOGGER.debug(
                "Observability DB write completed.",
                extra={"operation": operation_name, "call_id": self.call_id},
            )
        except Exception:
            _LOGGER.debug(
                "Observability write failed during %s for call_id=%s",
                operation_name,
                self.call_id,
                exc_info=True,
            )
