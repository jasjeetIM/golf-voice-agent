from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from voice_gateway.app.backend_client import BackendClient


def run(coro):
    return asyncio.run(coro)


def test_auth_headers_include_bearer_token() -> None:
    client = BackendClient(base_url="http://backend", api_key="secret")

    assert client._auth_headers() == {"Authorization": "Bearer secret"}

    run(client.close())


def test_post_sends_json_and_auth_header() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["json"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"ok": True})

    client = BackendClient(base_url="http://backend", api_key="secret")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = run(client._post("/v1/tools/search-tee-times", {"course_id": "course-1"}))

    assert result == {"ok": True}
    assert captured == {
        "method": "POST",
        "url": "http://backend/v1/tools/search-tee-times",
        "authorization": "Bearer secret",
        "json": {"course_id": "course-1"},
    }

    run(client.close())


def test_post_raises_for_non_success_status() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = BackendClient(base_url="http://backend", api_key="secret")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(httpx.HTTPStatusError):
        run(client._post("/v1/tools/search-tee-times", {"course_id": "course-1"}))

    run(client.close())


def test_endpoint_helpers_delegate_to_post() -> None:
    client = BackendClient(base_url="http://backend", api_key="secret")
    calls: list[str] = []

    async def fake_post(path: str, payload: dict[str, object]) -> dict[str, object]:
        del payload
        calls.append(path)
        return {"ok": True}

    client._post = fake_post  # type: ignore[assignment]

    run(client.search_tee_times({}))
    run(client.book_tee_time({}))
    run(client.modify_reservation({}))
    run(client.cancel_reservation({}))
    run(client.send_sms_confirmation({}))
    run(client.get_reservation_details({}))
    run(client.quote_reservation_change({}))
    run(client.check_slot_capacity({}))

    assert calls == [
        "/v1/tools/search-tee-times",
        "/v1/tools/book-tee-time",
        "/v1/tools/modify-reservation",
        "/v1/tools/cancel-reservation",
        "/v1/tools/send-sms-confirmation",
        "/v1/tools/get-reservation-details",
        "/v1/tools/quote-reservation-change",
        "/v1/tools/check-slot-capacity",
    ]

    run(client.close())
