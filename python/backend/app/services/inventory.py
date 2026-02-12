from __future__ import annotations

"""Inventory data access for tee time management."""

from typing import Any

import asyncpg

from shared.schemas import Money, SearchTeeTimesRequest, TeeTimeOption


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
        # Filter to a single course/date window and enforce live capacity limits.
        sql = """
            SELECT slot_id, start_ts, capacity_players, players_booked, base_price_cents, currency
            FROM tee_time_slots
            WHERE course_id = $1
              AND start_ts::date = $2::date
              AND start_ts::time >= $3::time
              AND start_ts::time <= $4::time
              AND is_closed = FALSE
              AND players_booked + $5 <= capacity_players
            ORDER BY start_ts
            LIMIT $6
        """
        rows = await conn.fetch(
            sql,
            req.course_id,
            req.date,
            req.time_window.start_local,
            req.time_window.end_local,
            req.players,
            req.max_results,
        )

        # Convert persistence rows into API contract models with derived fields.
        options: list[TeeTimeOption] = []
        for row in rows:
            start_ts = row["start_ts"]
            start_local = start_ts.isoformat()[11:16]
            base = row["base_price_cents"] or 0
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
        row = await conn.fetchrow(
            "SELECT * FROM tee_time_slots WHERE slot_id = $1 FOR UPDATE",
            slot_id,
        )
        return dict(row) if row else None

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
        return dict(row) if row else None

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
        return dict(row) if row else None
