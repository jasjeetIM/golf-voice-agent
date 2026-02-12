"""Connection-pool helpers for voice gateway observability writes."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import asyncpg

from ..config import settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    """Initializes the shared asyncpg connection pool exactly once."""
    global _pool
    if _pool is None:
        if not settings.DB_CONNECTION_STRING:
            raise RuntimeError("DB_CONNECTION_STRING is required for observability logging")
        _pool = await asyncpg.create_pool(settings.DB_CONNECTION_STRING, max_size=10)
    return _pool


async def get_pool() -> asyncpg.Pool:
    """Returns the existing connection pool, creating it when needed."""
    if _pool is None:
        return await init_pool()
    return _pool


async def close_pool() -> None:
    """Closes and clears the shared connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@contextlib.asynccontextmanager
async def get_conn() -> AsyncIterator[asyncpg.Connection]:
    """Yields a pooled connection for a single observability operation."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn
