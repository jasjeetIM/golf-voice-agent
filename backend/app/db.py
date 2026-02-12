from __future__ import annotations

import contextlib
from typing import AsyncIterator

import asyncpg

from .config import settings


_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.DB_CONNECTION_STRING,
            max_size=settings.DB_POOL_MAX,
        )
    return _pool


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        return await init_pool()
    return _pool


@contextlib.asynccontextmanager
async def get_conn() -> AsyncIterator[asyncpg.Connection]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


@contextlib.asynccontextmanager
async def transaction() -> AsyncIterator[asyncpg.Connection]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn
