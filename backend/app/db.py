from __future__ import annotations

"""Database pool and connection helpers for backend request handlers."""

import contextlib
from typing import AsyncIterator

import asyncpg

from .config import settings


_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    """Initializes the shared asyncpg pool when needed.

    Returns:
        The initialized asyncpg connection pool.
    """
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.DB_CONNECTION_STRING,
            max_size=settings.DB_POOL_MAX,
        )
    return _pool


async def get_pool() -> asyncpg.Pool:
    """Returns the shared asyncpg pool, creating it lazily if required."""
    if _pool is None:
        return await init_pool()
    return _pool


async def close_pool() -> None:
    """Closes the shared asyncpg pool during application shutdown."""
    global _pool
    if _pool is None:
        return
    await _pool.close()
    _pool = None


@contextlib.asynccontextmanager
async def get_conn() -> AsyncIterator[asyncpg.Connection]:
    """Yields a pooled connection for read or non-transactional operations."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


@contextlib.asynccontextmanager
async def transaction() -> AsyncIterator[asyncpg.Connection]:
    """Yields a pooled connection wrapped in a database transaction."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn
