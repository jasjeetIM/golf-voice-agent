"""HTTP client wrapper for calling backend tool endpoints."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

_LOGGER = logging.getLogger(__name__)


class BackendClient:
    """Thin async client used by the MCP bridge to call backend routes.

    The class intentionally keeps a narrow surface area and delegates all
    request/response handling to a single shared `_post` helper.
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        """Initializes the backend API client.

        Args:
            base_url: Backend API base URL.
            api_key: Bearer token expected by backend authentication middleware.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=15.0)

    def _auth_headers(self) -> dict[str, str]:
        """Builds request headers required by backend auth.

        Returns:
            Authorization header map for outgoing tool requests.
        """
        return {"Authorization": f"Bearer {self.api_key}"}

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Performs a POST request and returns parsed JSON body.

        Args:
            path: Absolute backend route path (for example `/v1/tools/...`).
            payload: JSON request payload.

        Raises:
            httpx.HTTPStatusError: If backend returns a non-2xx status.

        Returns:
            Parsed JSON response body.
        """
        started = time.monotonic()
        _LOGGER.debug(
            "Starting backend tool HTTP request.",
            extra={
                "path": path,
                "payload_keys": sorted(payload.keys()),
                "call_id": payload.get("call_id"),
            },
        )
        response = await self._client.post(
            f"{self.base_url}{path}",
            json=payload,
            headers=self._auth_headers(),
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        _LOGGER.debug(
            "Backend tool HTTP response received.",
            extra={
                "path": path,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
            },
        )
        response.raise_for_status()
        body = response.json()
        _LOGGER.debug(
            "Parsed backend tool HTTP response body.",
            extra={"path": path, "response_keys": sorted(body.keys()) if isinstance(body, dict) else None},
        )
        return body

    async def search_tee_times(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Calls backend search tee-times endpoint."""
        return await self._post("/v1/tools/search-tee-times", payload)

    async def book_tee_time(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Calls backend booking endpoint."""
        return await self._post("/v1/tools/book-tee-time", payload)

    async def modify_reservation(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Calls backend reservation-modification endpoint."""
        return await self._post("/v1/tools/modify-reservation", payload)

    async def cancel_reservation(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Calls backend reservation-cancel endpoint."""
        return await self._post("/v1/tools/cancel-reservation", payload)

    async def send_sms_confirmation(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Calls backend SMS confirmation endpoint."""
        return await self._post("/v1/tools/send-sms-confirmation", payload)

    async def get_reservation_details(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Calls backend reservation-details endpoint."""
        return await self._post("/v1/tools/get-reservation-details", payload)

    async def quote_reservation_change(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Calls backend reservation-change quote endpoint."""
        return await self._post("/v1/tools/quote-reservation-change", payload)

    async def check_slot_capacity(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Calls backend slot-capacity endpoint."""
        return await self._post("/v1/tools/check-slot-capacity", payload)

    async def close(self) -> None:
        """Closes the underlying HTTP client and frees connection resources."""
        _LOGGER.debug("Closing BackendClient HTTP session.")
        await self._client.aclose()
