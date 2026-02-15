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
        """Creates or refreshes the call row with known caller metadata."""
        await self._execute(
            operation_name="ensure_call",
            query="""
                INSERT INTO calls (call_id, from_number, to_number, started_at, session_id)
                VALUES ($1, $2, $3, now(), $4)
                ON CONFLICT (call_id) DO UPDATE
                SET from_number = CASE
                        WHEN calls.from_number = '' AND EXCLUDED.from_number <> '' THEN EXCLUDED.from_number
                        ELSE calls.from_number
                    END,
                    to_number = CASE
                        WHEN calls.to_number = '' AND EXCLUDED.to_number <> '' THEN EXCLUDED.to_number
                        ELSE calls.to_number
                    END,
                    session_id = COALESCE(calls.session_id, EXCLUDED.session_id)
            """,
            args=(self.call_id, from_number, to_number, self.session_id),
        )

    async def backfill_session_id(self, session_id: str) -> None:
        """Backfills a discovered session id across all call-scoped tables."""
        if not session_id:
            return
        try:
            async with get_conn() as conn:
                await conn.execute(
                    "UPDATE calls SET session_id = COALESCE(session_id, $2) WHERE call_id = $1",
                    self.call_id,
                    session_id,
                )
                await conn.execute(
                    "UPDATE session_events SET session_id = COALESCE(session_id, $2) WHERE call_id = $1",
                    self.call_id,
                    session_id,
                )
                await conn.execute(
                    "UPDATE realtime_items SET session_id = COALESCE(session_id, $2) WHERE call_id = $1",
                    self.call_id,
                    session_id,
                )
                await conn.execute(
                    "UPDATE tool_calls SET session_id = COALESCE(session_id, $2) WHERE call_id = $1",
                    self.call_id,
                    session_id,
                )
                await conn.execute(
                    "UPDATE mcp_calls SET session_id = COALESCE(session_id, $2) WHERE call_id = $1",
                    self.call_id,
                    session_id,
                )
        except Exception:
            _LOGGER.debug(
                "Failed to backfill session_id for call_id=%s",
                self.call_id,
                exc_info=True,
            )

    async def finalize_call(self, *, model: str | None = None) -> None:
        """Marks the call completed and stores final model/reservation linkage."""
        await self._execute(
            operation_name="finalize_call",
            query="""
                UPDATE calls
                SET ended_at = COALESCE(ended_at, now()),
                    session_id = COALESCE(session_id, $2),
                    model = COALESCE($3, model),
                    reservation_change = COALESCE(
                        (
                            SELECT change_id
                            FROM reservation_changes
                            WHERE call_id = $1
                            ORDER BY changed_at DESC
                            LIMIT 1
                        ),
                        reservation_change
                    )
                WHERE call_id = $1
            """,
            args=(self.call_id, self.session_id, model),
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
    ) -> None:
        """Upserts a realtime conversation item snapshot."""
        await self._execute(
            operation_name="upsert_realtime_item",
            query="""
                INSERT INTO realtime_items
                (item_id, call_id, session_id, role, type, status, content_json, tool_call_id, tool_name, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9, now())
                ON CONFLICT (item_id) DO UPDATE
                SET session_id = COALESCE(EXCLUDED.session_id, realtime_items.session_id),
                    role = EXCLUDED.role,
                    type = EXCLUDED.type,
                    status = EXCLUDED.status,
                    content_json = EXCLUDED.content_json,
                    tool_call_id = EXCLUDED.tool_call_id,
                    tool_name = EXCLUDED.tool_name,
                    updated_at = now()
            """,
            args=(
                item_id,
                self.call_id,
                self.session_id,
                content.get("role"),
                content.get("type"),
                content.get("status"),
                _to_jsonb(content),
                content.get("call_id"),
                content.get("name"),
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
        arguments_raw: str | None = None,
        output_raw: str | None = None,
        agent_name: str | None = None,
        latency_ms: int | None = None,
        reservation_id: str | None = None,
        change_id: str | None = None,
    ) -> None:
        """Persists a tool call lifecycle record."""
        if status in {"SUCCEEDED", "FAILED"} and tool_name in {
            "book_tee_time",
            "modify_reservation",
            "cancel_reservation",
        }:
            derived_reservation_id, derived_change_id = await self._derive_latest_reservation_change()
            reservation_id = reservation_id or derived_reservation_id
            change_id = change_id or derived_change_id
        await self._execute(
            operation_name="log_tool_call",
            query="""
                INSERT INTO tool_calls
                (call_id, session_id, tool_name, args_json, result_json, status, error_message,
                 latency_ms, reservation_id, change_id, tool_call_external_id, arguments_raw, output_raw, agent_name)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            """,
            args=(
                self.call_id,
                self.session_id,
                tool_name,
                _to_jsonb(args_json),
                _to_jsonb_or_none(result_json),
                status,
                error_message,
                latency_ms,
                reservation_id,
                change_id,
                tool_call_external_id,
                arguments_raw,
                output_raw,
                agent_name,
            ),
        )

    async def resolve_tool_call_reference(
        self,
        *,
        tool_name: str,
        args_json: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        """Finds the most likely tool_calls row for a given MCP invocation."""
        args_payload = _to_jsonb(args_json)
        try:
            async with get_conn() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT tool_call_id::text AS tool_call_id, tool_call_external_id
                    FROM tool_calls
                    WHERE call_id = $1
                      AND tool_name = $2::tool_name
                      AND (args_json @> $3::jsonb OR args_json <@ $3::jsonb)
                    ORDER BY started_at DESC
                    LIMIT 1
                    """,
                    self.call_id,
                    tool_name,
                    args_payload,
                )
                if row:
                    return row["tool_call_id"], row["tool_call_external_id"]
        except Exception:
            _LOGGER.debug(
                "Failed resolving tool call reference for call_id=%s tool_name=%s",
                self.call_id,
                tool_name,
                exc_info=True,
            )
        return None, None

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
        latency_ms: int | None = None,
    ) -> None:
        """Persists an MCP bridge call (request/response/error metadata)."""
        await self._execute(
            operation_name="log_mcp_call",
            query="""
                INSERT INTO mcp_calls
                (tool_call_id, tool_call_external_id, call_id, session_id, server_name, method, request_json, response_json, error_message, latency_ms)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
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
                latency_ms,
            ),
        )

    async def _derive_latest_reservation_change(self) -> tuple[str | None, str | None]:
        """Returns the latest reservation context for this call_id."""
        try:
            async with get_conn() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT reservation_id::text AS reservation_id, change_id::text AS change_id
                    FROM reservation_changes
                    WHERE call_id = $1
                    ORDER BY changed_at DESC
                    LIMIT 1
                    """,
                    self.call_id,
                )
                if row:
                    return row["reservation_id"], row["change_id"]
        except Exception:
            _LOGGER.debug(
                "Failed deriving reservation_change for call_id=%s",
                self.call_id,
                exc_info=True,
            )
        return None, None

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
