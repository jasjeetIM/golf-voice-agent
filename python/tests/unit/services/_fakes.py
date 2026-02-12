from __future__ import annotations

import asyncio
from typing import Any


class FakeConnection:
    """Minimal asyncpg-like connection for unit tests."""

    def __init__(
        self,
        *,
        fetch_results: list[list[dict[str, Any]]] | None = None,
        fetchrow_results: list[dict[str, Any] | None] | None = None,
        fetchval_results: list[Any] | None = None,
        execute_results: list[str] | None = None,
        in_transaction: bool = True,
    ) -> None:
        self._fetch_results = list(fetch_results or [])
        self._fetchrow_results = list(fetchrow_results or [])
        self._fetchval_results = list(fetchval_results or [])
        self._execute_results = list(execute_results or [])
        self._in_transaction = in_transaction

        self.calls: dict[str, list[tuple[str, tuple[Any, ...]]]] = {
            "fetch": [],
            "fetchrow": [],
            "fetchval": [],
            "execute": [],
        }

    def is_in_transaction(self) -> bool:
        return self._in_transaction

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        self.calls["fetch"].append((sql, args))
        if not self._fetch_results:
            return []
        return self._fetch_results.pop(0)

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        self.calls["fetchrow"].append((sql, args))
        if not self._fetchrow_results:
            return None
        return self._fetchrow_results.pop(0)

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.calls["fetchval"].append((sql, args))
        if not self._fetchval_results:
            return None
        return self._fetchval_results.pop(0)

    async def execute(self, sql: str, *args: Any) -> str:
        self.calls["execute"].append((sql, args))
        if not self._execute_results:
            return "OK"
        return self._execute_results.pop(0)


def run(coro: Any) -> Any:
    """Runs async coroutine in synchronous pytest tests."""
    return asyncio.run(coro)
