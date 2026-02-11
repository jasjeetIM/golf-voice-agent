from __future__ import annotations

import contextlib
from typing import AsyncIterator

import asyncpg

from ..config import settings


_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        if not settings.DB_CONNECTION_STRING:
            raise RuntimeError("DB_CONNECTION_STRING is required for observability logging")
        _pool = await asyncpg.create_pool(settings.DB_CONNECTION_STRING, max_size=10)
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
