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

    def __init__(self, call_id: str) -> None:
        self.call_id = call_id
        self.provider_session_id: str | None = None
        self.external_session_id: str | None = None
        _LOGGER.debug("DbLogger initialized.", extra={"call_id": call_id})

    def set_provider_session(
        self,
        *,
        provider_session_id: str | None,
        external_session_id: str | None = None,
    ) -> None:
        """Updates provider session context bound to future writes."""
        self.provider_session_id = provider_session_id
        self.external_session_id = external_session_id or self.external_session_id
        _LOGGER.debug(
            "DbLogger provider session context updated.",
            extra={
                "call_id": self.call_id,
                "provider_session_id": provider_session_id,
                "external_session_id": self.external_session_id,
            },
        )

    async def ensure_call(
        self,
        *,
        from_number: str,
        to_number: str,
        engine_mode: str,
        agent_provider: str | None,
        agent_model: str | None,
        stt_provider: str | None,
        stt_model: str | None,
        tts_provider: str | None,
        tts_model: str | None,
        realtime_provider: str | None,
        realtime_model: str | None,
    ) -> None:
        """Creates or refreshes the call row with known call metadata."""
        await self._execute(
            operation_name="ensure_call",
            query="""
                INSERT INTO calls (
                    call_id, from_number, to_number, started_at, engine_mode,
                    agent_provider, agent_model,
                    stt_provider, stt_model,
                    tts_provider, tts_model,
                    realtime_provider, realtime_model
                )
                VALUES ($1, $2, $3, now(), $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (call_id) DO UPDATE
                SET from_number = CASE
                        WHEN calls.from_number = '' AND EXCLUDED.from_number <> '' THEN EXCLUDED.from_number
                        ELSE calls.from_number
                    END,
                    to_number = CASE
                        WHEN calls.to_number = '' AND EXCLUDED.to_number <> '' THEN EXCLUDED.to_number
                        ELSE calls.to_number
                    END,
                    engine_mode = COALESCE(calls.engine_mode, EXCLUDED.engine_mode),
                    agent_provider = COALESCE(calls.agent_provider, EXCLUDED.agent_provider),
                    agent_model = COALESCE(calls.agent_model, EXCLUDED.agent_model),
                    stt_provider = COALESCE(calls.stt_provider, EXCLUDED.stt_provider),
                    stt_model = COALESCE(calls.stt_model, EXCLUDED.stt_model),
                    tts_provider = COALESCE(calls.tts_provider, EXCLUDED.tts_provider),
                    tts_model = COALESCE(calls.tts_model, EXCLUDED.tts_model),
                    realtime_provider = COALESCE(calls.realtime_provider, EXCLUDED.realtime_provider),
                    realtime_model = COALESCE(calls.realtime_model, EXCLUDED.realtime_model)
            """,
            args=(
                self.call_id,
                from_number,
                to_number,
                engine_mode,
                agent_provider,
                agent_model,
                stt_provider,
                stt_model,
                tts_provider,
                tts_model,
                realtime_provider,
                realtime_model,
            ),
        )

    async def ensure_provider_session(
        self,
        *,
        component: str,
        provider_name: str,
        external_session_id: str | None,
        model: str | None,
        metadata_json: dict[str, Any] | None,
    ) -> str | None:
        """Ensures provider session row exists and returns internal session id."""
        try:
            async with get_conn() as conn:
                row = None
                if external_session_id:
                    row = await conn.fetchrow(
                        """
                        SELECT provider_session_id::text AS provider_session_id
                        FROM provider_sessions
                        WHERE call_id = $1
                          AND component = $2
                          AND external_session_id = $3
                        ORDER BY started_at DESC
                        LIMIT 1
                        """,
                        self.call_id,
                        component,
                        external_session_id,
                    )
                else:
                    row = await conn.fetchrow(
                        """
                        SELECT provider_session_id::text AS provider_session_id
                        FROM provider_sessions
                        WHERE call_id = $1
                          AND component = $2
                          AND provider_name = $3
                        ORDER BY started_at DESC
                        LIMIT 1
                        """,
                        self.call_id,
                        component,
                        provider_name,
                    )

                if row:
                    provider_session_id = row["provider_session_id"]
                    await conn.execute(
                        """
                        UPDATE provider_sessions
                        SET external_session_id = COALESCE(external_session_id, $2),
                            model = COALESCE(model, $3),
                            metadata_json = COALESCE(metadata_json, '{}'::jsonb) || COALESCE($4::jsonb, '{}'::jsonb)
                        WHERE provider_session_id = $1::uuid
                        """,
                        provider_session_id,
                        external_session_id,
                        model,
                        _to_jsonb_or_none(metadata_json),
                    )
                else:
                    inserted = await conn.fetchrow(
                        """
                        INSERT INTO provider_sessions
                        (call_id, component, provider_name, external_session_id, model, metadata_json, started_at)
                        VALUES ($1, $2, $3, $4, $5, $6, now())
                        RETURNING provider_session_id::text AS provider_session_id
                        """,
                        self.call_id,
                        component,
                        provider_name,
                        external_session_id,
                        model,
                        _to_jsonb(metadata_json or {}),
                    )
                    provider_session_id = inserted["provider_session_id"]

                self.set_provider_session(
                    provider_session_id=provider_session_id,
                    external_session_id=external_session_id,
                )
                return provider_session_id
        except Exception:
            _LOGGER.debug(
                "Failed ensuring provider session for call_id=%s component=%s provider=%s",
                self.call_id,
                component,
                provider_name,
                exc_info=True,
            )
            fallback = self.provider_session_id
            self.set_provider_session(provider_session_id=fallback, external_session_id=external_session_id)
            return fallback

    async def finalize_call(self) -> None:
        """Marks call completion and stores latest reservation change linkage."""
        await self._execute(
            operation_name="finalize_call",
            query="""
                UPDATE calls
                SET ended_at = COALESCE(ended_at, now()),
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
            args=(self.call_id,),
        )
        if self.provider_session_id:
            await self._execute(
                operation_name="finalize_provider_session",
                query="""
                    UPDATE provider_sessions
                    SET ended_at = COALESCE(ended_at, now())
                    WHERE provider_session_id = $1::uuid
                """,
                args=(self.provider_session_id,),
            )

    async def log_call_event(
        self,
        *,
        event_name: str,
        payload: dict[str, Any] | None = None,
        direction: str | None = None,
        source: str | None = None,
        transport_provider: str | None = None,
        external_event_id: str | None = None,
    ) -> None:
        """Persists low-level call transport events."""
        await self._execute(
            operation_name="log_call_event",
            query="""
                INSERT INTO call_events
                (call_id, event_name, direction, source, transport_provider, external_event_id, payload_json)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            args=(
                self.call_id,
                event_name,
                direction,
                source,
                transport_provider,
                external_event_id,
                _to_jsonb(payload or {}),
            ),
        )

    async def log_session_event(
        self,
        *,
        event_name: str,
        component: str,
        provider_name: str,
        payload: dict[str, Any] | None = None,
        external_event_type: str | None = None,
        external_event_id: str | None = None,
        direction: str | None = None,
        item_id: str | None = None,
        tool_call_id: str | None = None,
        agent_name: str | None = None,
        turn_index: int | None = None,
        latency_ms: int | None = None,
    ) -> None:
        """Persists normalized provider/session events."""
        await self._execute(
            operation_name="log_session_event",
            query="""
                INSERT INTO session_events (
                    call_id,
                    provider_session_id,
                    component,
                    provider_name,
                    agent_name,
                    event_name,
                    external_event_type,
                    external_event_id,
                    direction,
                    item_id,
                    tool_call_id,
                    turn_index,
                    latency_ms,
                    payload_json
                )
                VALUES ($1,$2::uuid,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            """,
            args=(
                self.call_id,
                self.provider_session_id,
                component,
                provider_name,
                agent_name,
                event_name,
                external_event_type,
                external_event_id,
                direction,
                item_id,
                tool_call_id,
                turn_index,
                latency_ms,
                _to_jsonb(payload or {}),
            ),
        )

    async def upsert_conversation_item(
        self,
        *,
        external_item_id: str,
        component: str,
        provider_name: str,
        role: str | None,
        modality: str | None,
        item_type: str | None,
        status: str | None,
        content: dict[str, Any],
        tool_call_id: str | None,
        tool_name: str | None,
    ) -> None:
        """Upserts provider conversation artifact snapshots."""
        if self.provider_session_id:
            await self._execute(
                operation_name="upsert_conversation_item",
                query="""
                    INSERT INTO conversation_items (
                        call_id, provider_session_id, external_item_id, component, provider_name,
                        role, modality, item_type, status, content_json, tool_call_id, tool_name,
                        created_at, updated_at
                    )
                    VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, now(), now())
                    ON CONFLICT (call_id, provider_session_id, external_item_id) DO UPDATE
                    SET role = EXCLUDED.role,
                        modality = EXCLUDED.modality,
                        item_type = EXCLUDED.item_type,
                        status = EXCLUDED.status,
                        content_json = EXCLUDED.content_json,
                        tool_call_id = EXCLUDED.tool_call_id,
                        tool_name = EXCLUDED.tool_name,
                        updated_at = now()
                """,
                args=(
                    self.call_id,
                    self.provider_session_id,
                    external_item_id,
                    component,
                    provider_name,
                    role,
                    modality,
                    item_type,
                    status,
                    _to_jsonb(content),
                    tool_call_id,
                    tool_name,
                ),
            )
            return

        await self._execute(
            operation_name="insert_conversation_item",
            query="""
                INSERT INTO conversation_items (
                    call_id, provider_session_id, external_item_id, component, provider_name,
                    role, modality, item_type, status, content_json, tool_call_id, tool_name,
                    created_at, updated_at
                )
                VALUES ($1, NULL, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, now(), now())
            """,
            args=(
                self.call_id,
                external_item_id,
                component,
                provider_name,
                role,
                modality,
                item_type,
                status,
                _to_jsonb(content),
                tool_call_id,
                tool_name,
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
        provider_name: str | None = None,
        component: str | None = None,
        turn_index: int | None = None,
    ) -> None:
        """Persists tool call lifecycle records."""
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
                INSERT INTO tool_calls (
                    call_id, provider_session_id, turn_index, tool_name,
                    args_json, result_json, status, error_message,
                    started_at, latency_ms, reservation_id, change_id,
                    tool_call_external_id, arguments_raw, output_raw,
                    agent_name, provider_name, component
                )
                VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8, now(), $9, $10, $11, $12, $13, $14, $15, $16, $17)
            """,
            args=(
                self.call_id,
                self.provider_session_id,
                turn_index,
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
                provider_name,
                component,
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
                if self.provider_session_id:
                    row = await conn.fetchrow(
                        """
                        SELECT tool_call_id::text AS tool_call_id, tool_call_external_id
                        FROM tool_calls
                        WHERE call_id = $1
                          AND provider_session_id = $2::uuid
                          AND tool_name = $3
                          AND (args_json @> $4::jsonb OR args_json <@ $4::jsonb)
                        ORDER BY started_at DESC
                        LIMIT 1
                        """,
                        self.call_id,
                        self.provider_session_id,
                        tool_name,
                        args_payload,
                    )
                else:
                    row = await conn.fetchrow(
                        """
                        SELECT tool_call_id::text AS tool_call_id, tool_call_external_id
                        FROM tool_calls
                        WHERE call_id = $1
                          AND tool_name = $2
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
        tool_name: str,
        server_name: str,
        method: str,
        request_json: dict[str, Any] | None,
        response_json: dict[str, Any] | None,
        error_message: str | None,
        latency_ms: int | None = None,
    ) -> None:
        """Persists MCP bridge request/response metadata."""
        await self._execute(
            operation_name="log_mcp_call",
            query="""
                INSERT INTO mcp_calls
                (tool_call_id, tool_call_external_id, tool_name, call_id, provider_session_id, server_name, method,
                 request_json, response_json, error_message, started_at, latency_ms)
                VALUES ($1::uuid,$2,$3,$4,$5::uuid,$6,$7,$8,$9,$10,now(),$11)
            """,
            args=(
                tool_call_id,
                tool_call_external_id,
                tool_name,
                self.call_id,
                self.provider_session_id,
                server_name,
                method,
                _to_jsonb(request_json or {}),
                _to_jsonb(response_json or {}),
                error_message,
                latency_ms,
            ),
        )

    async def _derive_latest_reservation_change(self) -> tuple[str | None, str | None]:
        """Returns latest reservation context associated with this call."""
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
        """Runs one SQL write, swallowing failures to avoid call interruption."""
        _LOGGER.debug(
            "Executing observability DB write.",
            extra={"operation": operation_name, "call_id": self.call_id, "arg_count": len(args)},
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
