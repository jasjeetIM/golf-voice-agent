"""Connection-pool helpers for voice gateway observability writes."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

import asyncpg

from ..config import settings

_LOGGER = logging.getLogger(__name__)
_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    """Initializes the shared asyncpg connection pool exactly once."""
    global _pool
    if _pool is None:
        if not settings.DB_CONNECTION_STRING:
            raise RuntimeError("DB_CONNECTION_STRING is required for observability logging")
        _LOGGER.debug("Creating observability DB pool.")
        _pool = await asyncpg.create_pool(settings.DB_CONNECTION_STRING, max_size=10)
        _LOGGER.debug("Observability DB pool created.")
    else:
        _LOGGER.debug("Reusing existing observability DB pool.")
    return _pool


async def get_pool() -> asyncpg.Pool:
    """Returns the existing connection pool, creating it when needed."""
    if _pool is None:
        _LOGGER.debug("Observability DB pool not initialized; calling init_pool().")
        return await init_pool()
    _LOGGER.debug("Returning initialized observability DB pool.")
    return _pool


async def close_pool() -> None:
    """Closes and clears the shared connection pool."""
    global _pool
    if _pool is not None:
        _LOGGER.debug("Closing observability DB pool.")
        await _pool.close()
        _pool = None
        _LOGGER.debug("Observability DB pool closed.")


@contextlib.asynccontextmanager
async def get_conn() -> AsyncIterator[asyncpg.Connection]:
    """Yields a pooled connection for a single observability operation."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn
