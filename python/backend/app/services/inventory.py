from __future__ import annotations

from typing import Any

import asyncpg

from shared.schemas import SearchTeeTimesRequest, TeeTimeOption, Money


class InventoryStore:
    async def search(self, conn: asyncpg.Connection, req: SearchTeeTimesRequest) -> list[TeeTimeOption]:
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
        options: list[TeeTimeOption] = []
        for row in rows:
            start_ts = row["start_ts"]
            start_local = start_ts.isoformat()[11:16]
            base = row["base_price_cents"] or 0
            options.append(
                TeeTimeOption(
                    slot_id=str(row["slot_id"]),
                    start_local=start_local,
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

    async def get_slot_for_update(self, conn: asyncpg.Connection, slot_id: str) -> dict[str, Any] | None:
        row = await conn.fetchrow(
            "SELECT * FROM tee_time_slots WHERE slot_id = $1 FOR UPDATE",
            slot_id,
        )
        return dict(row) if row else None

    async def increment_players_booked(
        self, conn: asyncpg.Connection, slot_id: str, players: int
    ) -> dict[str, Any] | None:
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
