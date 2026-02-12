from __future__ import annotations

from typing import Any

import httpx


class BackendClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=15.0)

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await self._client.post(
            f"{self.base_url}{path}",
            json=payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        resp.raise_for_status()
        return resp.json()

    async def search_tee_times(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/v1/tools/search-tee-times", payload)

    async def book_tee_time(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/v1/tools/book-tee-time", payload)

    async def modify_reservation(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/v1/tools/modify-reservation", payload)

    async def cancel_reservation(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/v1/tools/cancel-reservation", payload)

    async def send_sms_confirmation(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/v1/tools/send-sms-confirmation", payload)

    async def get_reservation_details(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/v1/tools/get-reservation-details", payload)

    async def quote_reservation_change(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/v1/tools/quote-reservation-change", payload)

    async def check_slot_capacity(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/v1/tools/check-slot-capacity", payload)

    async def close(self) -> None:
        await self._client.aclose()
