"""Database pool and connection helpers for backend request handlers."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from typing import AsyncIterator

import asyncpg

from .config import settings

_LOGGER = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    """Initializes the shared asyncpg pool when needed.

    Returns:
        The initialized asyncpg connection pool.
    """
    global _pool
    if _pool is None:
        _LOGGER.debug("Creating backend DB pool.", extra={"max_size": settings.DB_POOL_MAX})
        _pool = await asyncpg.create_pool(
            settings.DB_CONNECTION_STRING,
            max_size=settings.DB_POOL_MAX,
        )
        _LOGGER.debug("Backend DB pool created.")
    else:
        _LOGGER.debug("Reusing existing backend DB pool.")
    return _pool


async def get_pool() -> asyncpg.Pool:
    """Returns the shared asyncpg pool, creating it lazily if required."""
    if _pool is None:
        _LOGGER.debug("Backend DB pool not initialized; calling init_pool().")
        return await init_pool()
    _LOGGER.debug("Returning initialized backend DB pool.")
    return _pool


async def close_pool() -> None:
    """Closes the shared asyncpg pool during application shutdown."""
    global _pool
    if _pool is None:
        _LOGGER.debug("Backend DB pool close requested with no active pool.")
        return
    _LOGGER.debug("Closing backend DB pool.")
    await _pool.close()
    _pool = None
    _LOGGER.debug("Backend DB pool closed.")


@asynccontextmanager
async def get_conn() -> AsyncIterator[asyncpg.Connection]:
    """Yields a pooled connection for read or non-transactional operations."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def transaction() -> AsyncIterator[asyncpg.Connection]:
    """Yields a pooled connection wrapped in a database transaction."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn
