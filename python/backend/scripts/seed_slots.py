from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import asyncpg


async def main() -> None:
    connection_string = os.getenv("DB_CONNECTION_STRING", "postgres://localhost:5432/postgres")
    pool = await asyncpg.create_pool(connection_string)

    tee_time_start_hour = int(os.getenv("TEE_TIME_START_HOUR", "7"))
    tee_time_end_hour = int(os.getenv("TEE_TIME_END_HOUR", "15"))
    slot_interval_minutes = int(os.getenv("SLOT_INTERVAL_MINUTES", "12"))
    forward_days = int(os.getenv("FORWARD_OPEN_TEE_TIME_DAYS", "14"))

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO courses (course_id, course_name, timezone)
                VALUES ($1, $2, $3)
                ON CONFLICT (course_id) DO NOTHING
                """,
                "0",
                "Demo Course 0",
                "America/New_York",
            )

            total = 0
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

            for day_offset in range(1, forward_days + 1):
                day = today + timedelta(days=day_offset)

                start_minutes = tee_time_start_hour * 60
                end_minutes = tee_time_end_hour * 60
                m = start_minutes
                while m <= end_minutes:
                    hour = m // 60
                    minute = m % 60
                    price_cents = 10000 if m < 15 * 60 else 5000
                    start_ts = datetime(
                        day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc
                    )

                    await conn.execute(
                        """
                        INSERT INTO tee_time_slots
                        (course_id, start_ts, capacity_players, base_price_cents, currency, is_closed, players_booked)
                        VALUES ($1, $2, $3, $4, 'USD', FALSE, 0)
                        ON CONFLICT (course_id, start_ts) DO UPDATE
                        SET base_price_cents = EXCLUDED.base_price_cents,
                            updated_at = now()
                        """,
                        "0",
                        start_ts,
                        4,
                        price_cents,
                    )
                    total += 1
                    m += slot_interval_minutes

            print(
                f"Inserted/updated {total} slots for course 0 over the next {forward_days} days "
                f"({tee_time_start_hour}am-{tee_time_end_hour}pm, {slot_interval_minutes}-min cadence)."
            )

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
