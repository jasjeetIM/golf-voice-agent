from __future__ import annotations

"""Seeds demo golf course tee-time slots for local development.

This script inserts (or updates) a demo course and its upcoming tee-time slots.
"""

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import asyncpg


DEFAULT_DB_CONNECTION_STRING = "postgresql://postgres:postgres@localhost:5432/golf"
DEFAULT_COURSE_ID = "0"
DEFAULT_COURSE_NAME = "Demo Course 0"
DEFAULT_COURSE_TIMEZONE = "America/New_York"
DEFAULT_TEE_TIME_START_HOUR = 7
DEFAULT_TEE_TIME_END_HOUR = 15
DEFAULT_SLOT_INTERVAL_MINUTES = 12
DEFAULT_FORWARD_DAYS = 14
DEFAULT_CAPACITY_PLAYERS = 4
DEFAULT_REGULAR_PRICE_CENTS = 10000
DEFAULT_TWILIGHT_PRICE_CENTS = 5000
DEFAULT_TWILIGHT_START_HOUR = 15


@dataclass(frozen=True)
class SeedConfig:
    """Runtime configuration for tee-time slot seeding."""

    db_connection_string: str
    course_id: str
    course_name: str
    course_timezone: str
    tee_time_start_hour: int
    tee_time_end_hour: int
    slot_interval_minutes: int
    forward_days: int
    capacity_players: int
    regular_price_cents: int
    twilight_price_cents: int
    twilight_start_hour: int

    @classmethod
    def from_env(cls) -> "SeedConfig":
        """Builds seeding configuration from environment variables."""
        return cls(
            db_connection_string=os.getenv(
                "DB_CONNECTION_STRING",
                DEFAULT_DB_CONNECTION_STRING,
            ),
            course_id=os.getenv("SEED_COURSE_ID", DEFAULT_COURSE_ID),
            course_name=os.getenv("SEED_COURSE_NAME", DEFAULT_COURSE_NAME),
            course_timezone=os.getenv("SEED_COURSE_TIMEZONE", DEFAULT_COURSE_TIMEZONE),
            tee_time_start_hour=_get_env_int(
                "TEE_TIME_START_HOUR",
                DEFAULT_TEE_TIME_START_HOUR,
            ),
            tee_time_end_hour=_get_env_int(
                "TEE_TIME_END_HOUR",
                DEFAULT_TEE_TIME_END_HOUR,
            ),
            slot_interval_minutes=_get_env_int(
                "SLOT_INTERVAL_MINUTES",
                DEFAULT_SLOT_INTERVAL_MINUTES,
            ),
            forward_days=_get_env_int(
                "FORWARD_OPEN_TEE_TIME_DAYS",
                DEFAULT_FORWARD_DAYS,
            ),
            capacity_players=_get_env_int(
                "SLOT_CAPACITY_PLAYERS",
                DEFAULT_CAPACITY_PLAYERS,
            ),
            regular_price_cents=_get_env_int(
                "REGULAR_PRICE_CENTS",
                DEFAULT_REGULAR_PRICE_CENTS,
            ),
            twilight_price_cents=_get_env_int(
                "TWILIGHT_PRICE_CENTS",
                DEFAULT_TWILIGHT_PRICE_CENTS,
            ),
            twilight_start_hour=_get_env_int(
                "TWILIGHT_START_HOUR",
                DEFAULT_TWILIGHT_START_HOUR,
            ),
        )


def _get_env_int(name: str, default: int) -> int:
    """Reads an integer environment variable with validation.

    Args:
        name: Environment variable name.
        default: Fallback value when the variable is missing.

    Returns:
        Parsed integer value.

    Raises:
        ValueError: If the configured value is not a valid integer.
    """
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got: {raw_value}") from exc


def validate_config(config: SeedConfig) -> None:
    """Validates seeding configuration before any database writes.

    Args:
        config: Runtime seeding configuration.

    Raises:
        ValueError: If configuration values are outside valid bounds.
    """
    if not (0 <= config.tee_time_start_hour <= 23):
        raise ValueError("TEE_TIME_START_HOUR must be between 0 and 23")
    if not (0 <= config.tee_time_end_hour <= 23):
        raise ValueError("TEE_TIME_END_HOUR must be between 0 and 23")
    if config.tee_time_end_hour < config.tee_time_start_hour:
        raise ValueError("TEE_TIME_END_HOUR must be >= TEE_TIME_START_HOUR")
    if config.slot_interval_minutes <= 0:
        raise ValueError("SLOT_INTERVAL_MINUTES must be > 0")
    if config.forward_days <= 0:
        raise ValueError("FORWARD_OPEN_TEE_TIME_DAYS must be > 0")
    if config.capacity_players <= 0:
        raise ValueError("SLOT_CAPACITY_PLAYERS must be > 0")
    if config.regular_price_cents < 0 or config.twilight_price_cents < 0:
        raise ValueError("Price values must be >= 0")
    if not (0 <= config.twilight_start_hour <= 23):
        raise ValueError("TWILIGHT_START_HOUR must be between 0 and 23")

    # Validate timezone eagerly so failures occur before DB writes.
    ZoneInfo(config.course_timezone)


def iter_slot_minutes(config: SeedConfig):
    """Yields minute-of-day values for each slot in the daily schedule."""
    minute_of_day = config.tee_time_start_hour * 60
    end_minute_of_day = config.tee_time_end_hour * 60

    while minute_of_day <= end_minute_of_day:
        yield minute_of_day
        minute_of_day += config.slot_interval_minutes


def get_price_cents(config: SeedConfig, minute_of_day: int) -> int:
    """Returns price for a slot based on configured twilight cutoff."""
    if minute_of_day < config.twilight_start_hour * 60:
        return config.regular_price_cents
    return config.twilight_price_cents


def iter_slot_start_times_utc(config: SeedConfig):
    """Yields UTC slot start timestamps derived from course-local schedule.

    The schedule is generated in local course time first, then converted to UTC
    for storage. This avoids the common bug of treating local schedule hours as
    UTC hours directly.
    """
    local_tz = ZoneInfo(config.course_timezone)
    local_today = datetime.now(timezone.utc).astimezone(local_tz).date()

    for day_offset in range(1, config.forward_days + 1):
        local_day = local_today + timedelta(days=day_offset)
        for minute_of_day in iter_slot_minutes(config):
            hour, minute = divmod(minute_of_day, 60)
            local_start = datetime(
                local_day.year,
                local_day.month,
                local_day.day,
                hour,
                minute,
                tzinfo=local_tz,
            )
            yield local_start.astimezone(timezone.utc), minute_of_day


async def upsert_course(conn: asyncpg.Connection, config: SeedConfig) -> None:
    """Inserts or updates the seeded course metadata."""
    await conn.execute(
        """
        INSERT INTO courses (course_id, course_name, timezone)
        VALUES ($1, $2, $3)
        ON CONFLICT (course_id) DO UPDATE
        SET course_name = EXCLUDED.course_name,
            timezone = EXCLUDED.timezone,
            updated_at = now()
        """,
        config.course_id,
        config.course_name,
        config.course_timezone,
    )


async def upsert_slot(
    conn: asyncpg.Connection,
    config: SeedConfig,
    start_ts: datetime,
    price_cents: int,
) -> None:
    """Upserts a single tee-time slot."""
    await conn.execute(
        """
        INSERT INTO tee_time_slots
        (
            course_id,
            start_ts,
            capacity_players,
            base_price_cents,
            currency,
            is_closed,
            players_booked
        )
        VALUES ($1, $2, $3, $4, 'USD', FALSE, 0)
        ON CONFLICT (course_id, start_ts) DO UPDATE
        SET capacity_players = EXCLUDED.capacity_players,
            base_price_cents = EXCLUDED.base_price_cents,
            updated_at = now()
        """,
        config.course_id,
        start_ts,
        config.capacity_players,
        price_cents,
    )


async def seed_slots(conn: asyncpg.Connection, config: SeedConfig) -> int:
    """Seeds all configured slot timestamps and returns the total row count."""
    total = 0
    for start_ts_utc, minute_of_day in iter_slot_start_times_utc(config):
        price_cents = get_price_cents(config, minute_of_day)
        await upsert_slot(conn, config, start_ts_utc, price_cents)
        total += 1
    return total


def build_summary(config: SeedConfig, total: int) -> str:
    """Builds a user-readable completion summary."""
    return (
        f"Inserted/updated {total} slots for course {config.course_id} over the next "
        f"{config.forward_days} days "
        f"({config.tee_time_start_hour}:00-{config.tee_time_end_hour}:00 local, "
        f"{config.slot_interval_minutes}-min cadence, timezone={config.course_timezone})."
    )


async def main() -> None:
    """Entry point for CLI execution."""
    config = SeedConfig.from_env()
    validate_config(config)

    pool = await asyncpg.create_pool(config.db_connection_string)
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await upsert_course(conn, config)
                total = await seed_slots(conn, config)
        print(build_summary(config, total))
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
