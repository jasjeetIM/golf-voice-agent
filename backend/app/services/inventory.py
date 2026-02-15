"""Inventory data access for tee time management."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import asyncpg

from shared.schemas import Money, SearchTeeTimesRequest, TeeTimeOption

_LOGGER = logging.getLogger(__name__)


class InventoryStore:
    """Persistence operations for tee-time slot inventory."""

    async def search(
        self,
        conn: asyncpg.Connection,
        req: SearchTeeTimesRequest,
    ) -> list[TeeTimeOption]:
        """Searches for available tee-time slots matching caller constraints.

        Args:
            conn: Active database connection.
            req: Validated search criteria from the API layer.

        Returns:
            A list of user-facing tee-time options sorted by start time.
        """
        _LOGGER.debug(
            "InventoryStore.search() called.",
            extra={
                "course_id": req.course_id,
                "date": req.date,
                "start_local": req.time_window.start_local,
                "end_local": req.time_window.end_local,
                "players": req.players,
                "max_results": req.max_results,
                "holes": req.holes,
                "reservation_type": req.reservation_type,
                "call_id": req.call_id,
            },
        )
        search_date = date.fromisoformat(req.date)
        # Filter to a single course/date window and enforce live capacity limits.
        sql = """
            SELECT
                s.slot_id,
                s.start_ts,
                s.capacity_players,
                s.players_booked,
                s.base_price_cents,
                s.currency,
                to_char((s.start_ts AT TIME ZONE c.timezone), 'HH24:MI') AS start_local
            FROM tee_time_slots s
            JOIN courses c ON c.course_id = s.course_id
            WHERE s.course_id = $1
              AND (s.start_ts AT TIME ZONE c.timezone)::date = $2::date
              AND (s.start_ts AT TIME ZONE c.timezone)::time >= $3::time
              AND (s.start_ts AT TIME ZONE c.timezone)::time <= $4::time
              AND s.is_closed = FALSE
              AND s.players_booked + $5 <= s.capacity_players
            ORDER BY s.start_ts
            LIMIT $6
        """
        rows = await conn.fetch(
            sql,
            req.course_id,
            search_date,
            req.time_window.start_local,
            req.time_window.end_local,
            req.players,
            req.max_results,
        )
        _LOGGER.debug(
            "InventoryStore.search() DB read complete.",
            extra={
                "row_count": len(rows),
                "course_id": req.course_id,
                "date": search_date.isoformat(),
            },
        )

        # Convert persistence rows into API contract models with derived fields.
        options: list[TeeTimeOption] = []
        for row in rows:
            start_ts = row["start_ts"]
            start_local = row.get("start_local") or start_ts.isoformat()[11:16]
            base = row["base_price_cents"] or 0
            _LOGGER.debug(
                "InventoryStore.search() processing row.",
                extra={
                    "slot_id": str(row["slot_id"]),
                    "start_ts": start_ts.isoformat() if start_ts else None,
                    "start_local": start_local,
                    "capacity_players": row["capacity_players"],
                    "players_booked": row["players_booked"],
                    "base_price_cents": base,
                    "currency": row["currency"],
                },
            )
            options.append(
                TeeTimeOption(
                    slot_id=str(row["slot_id"]),
                    start_local=start_local,
                    # Current business rule: tee-time slots are sold as 4-hour rounds.
                    duration_min=240,
                    players_allowed=[
                        p
                        for p in [1, 2, 3, 4]
                        if p + row["players_booked"] <= row["capacity_players"]
                    ],
                    price=Money(
                        currency=row["currency"] or "USD",
                        amount_per_player=base / 100,
                        amount_total=(base / 100) * req.players,
                    ),
                    constraints={
                        "cart_required": False,
                        "cancellation_policy": "Cancel >= 24h to avoid fee",
                    },
                )
            )
        _LOGGER.debug(
            "InventoryStore.search() returning options.",
            extra={
                "option_count": len(options),
                "course_id": req.course_id,
                "date": search_date.isoformat(),
            },
        )
        return options

    async def get_slot_for_update(
        self,
        conn: asyncpg.Connection,
        slot_id: str,
    ) -> dict[str, Any] | None:
        """Fetches and row-locks a slot for atomic inventory mutation.

        Args:
            conn: Active database connection.
            slot_id: Target tee-time slot identifier.

        Returns:
            The locked slot row as a dictionary, or ``None`` when not found.
        """
        _LOGGER.debug(
            "InventoryStore.get_slot_for_update() called.",
            extra={"slot_id": slot_id},
        )
        row = await conn.fetchrow(
            "SELECT * FROM tee_time_slots WHERE slot_id = $1 FOR UPDATE",
            slot_id,
        )
        slot = dict(row) if row else None
        _LOGGER.debug(
            "InventoryStore.get_slot_for_update() DB read complete.",
            extra={
                "slot_id": slot_id,
                "found": slot is not None,
                "slot_row": slot,
            },
        )
        return slot

    async def increment_players_booked(
        self, conn: asyncpg.Connection, slot_id: str, players: int
    ) -> dict[str, Any] | None:
        """Adds players to a slot when capacity constraints permit.

        Args:
            conn: Active database connection.
            slot_id: Target tee-time slot identifier.
            players: Number of players to add.

        Returns:
            Updated slot row, or ``None`` when capacity or open-state checks fail.
        """
        _LOGGER.debug(
            "InventoryStore.increment_players_booked() called.",
            extra={"slot_id": slot_id, "players_to_add": players},
        )
        # Capacity and open/closed checks are embedded in the UPDATE predicate.
        row = await conn.fetchrow(
            """
            UPDATE tee_time_slots
            SET players_booked = players_booked + $2, updated_at = now()
            WHERE slot_id = $1 AND players_booked + $2 <= capacity_players AND is_closed = FALSE
            RETURNING *
            """,
            slot_id,
            players,
        )
        slot = dict(row) if row else None
        _LOGGER.debug(
            "InventoryStore.increment_players_booked() DB write complete.",
            extra={
                "slot_id": slot_id,
                "players_to_add": players,
                "updated": slot is not None,
                "slot_row": slot,
            },
        )
        return slot

    async def decrement_players_booked(
        self, conn: asyncpg.Connection, slot_id: str, players: int
    ) -> dict[str, Any] | None:
        """Decrements booked players on a slot, never dropping below zero.

        Args:
            conn: Active database connection.
            slot_id: Target tee-time slot identifier.
            players: Number of players to remove.

        Returns:
            Updated slot row, or ``None`` when the slot does not exist.
        """
        _LOGGER.debug(
            "InventoryStore.decrement_players_booked() called.",
            extra={"slot_id": slot_id, "players_to_remove": players},
        )
        row = await conn.fetchrow(
            """
            UPDATE tee_time_slots
            SET players_booked = GREATEST(players_booked - $2, 0), updated_at = now()
            WHERE slot_id = $1
            RETURNING *
            """,
            slot_id,
            players,
        )
        slot = dict(row) if row else None
        _LOGGER.debug(
            "InventoryStore.decrement_players_booked() DB write complete.",
            extra={
                "slot_id": slot_id,
                "players_to_remove": players,
                "updated": slot is not None,
                "slot_row": slot,
            },
        )
        return slot
