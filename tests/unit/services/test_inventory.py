from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest
from pydantic import ValidationError

from backend.app.services.inventory import InventoryStore
from shared.schemas import ReservationType, SearchTeeTimesRequest, TimeWindow

from ._fakes import FakeConnection, run


def build_search_request() -> SearchTeeTimesRequest:
    return SearchTeeTimesRequest(
        date="2026-03-01",
        time_window=TimeWindow(start_local="08:00", end_local="11:00"),
        players=2,
        holes=18,
        reservation_type=ReservationType.WALKING,
        max_results=5,
    )


def test_search_request_rejects_invalid_date_format() -> None:
    with pytest.raises(ValidationError):
        SearchTeeTimesRequest(
            date="03-01-2026",
            time_window=TimeWindow(start_local="08:00", end_local="11:00"),
            players=2,
            holes=18,
            reservation_type=ReservationType.WALKING,
            max_results=5,
        )


def test_search_returns_transformed_tee_time_options() -> None:
    store = InventoryStore()
    conn = FakeConnection(
        fetch_results=[
            [
                {
                    "slot_id": "slot-1",
                    "start_ts": datetime(2026, 3, 1, 13, 24, tzinfo=timezone.utc),
                    "capacity_players": 4,
                    "players_booked": 1,
                    "base_price_cents": 12000,
                    "currency": "USD",
                }
            ]
        ]
    )

    result = run(store.search(conn, build_search_request(), course_id="course-1"))

    assert len(result) == 1
    assert result[0].slot_id == "slot-1"
    assert result[0].start_local == "13:24"
    assert result[0].price.amount_per_player == 120.0
    assert result[0].price.amount_total == 240.0
    assert result[0].players_allowed == [1, 2, 3]
    assert "FROM tee_time_slots" in conn.calls["fetch"][0][0]
    assert conn.calls["fetch"][0][1][1] == date(2026, 3, 1)
    assert conn.calls["fetch"][0][1][2] == time(8, 0)
    assert conn.calls["fetch"][0][1][3] == time(11, 0)


def test_get_slot_for_update_returns_dict_when_found() -> None:
    store = InventoryStore()
    conn = FakeConnection(
        fetchrow_results=[
            {
                "slot_id": "slot-1",
                "players_booked": 2,
                "capacity_players": 4,
                "is_closed": False,
            }
        ]
    )

    result = run(store.get_slot_for_update(conn, "slot-1"))

    assert result is not None
    assert result["slot_id"] == "slot-1"
    assert "FOR UPDATE" in conn.calls["fetchrow"][0][0]


def test_get_slot_for_update_returns_none_when_missing() -> None:
    store = InventoryStore()
    conn = FakeConnection(fetchrow_results=[None])

    result = run(store.get_slot_for_update(conn, "missing-slot"))

    assert result is None


def test_increment_players_booked_returns_updated_row() -> None:
    store = InventoryStore()
    conn = FakeConnection(
        fetchrow_results=[
            {
                "slot_id": "slot-1",
                "players_booked": 3,
                "capacity_players": 4,
                "is_closed": False,
            }
        ]
    )

    result = run(store.increment_players_booked(conn, "slot-1", 2))

    assert result is not None
    assert result["players_booked"] == 3
    assert "players_booked = players_booked + $2" in conn.calls["fetchrow"][0][0]


def test_increment_players_booked_returns_none_when_constraints_fail() -> None:
    store = InventoryStore()
    conn = FakeConnection(fetchrow_results=[None])

    result = run(store.increment_players_booked(conn, "slot-1", 2))

    assert result is None


def test_decrement_players_booked_returns_updated_row() -> None:
    store = InventoryStore()
    conn = FakeConnection(
        fetchrow_results=[
            {
                "slot_id": "slot-1",
                "players_booked": 1,
                "capacity_players": 4,
                "is_closed": False,
            }
        ]
    )

    result = run(store.decrement_players_booked(conn, "slot-1", 2))

    assert result is not None
    assert result["players_booked"] == 1
    assert "GREATEST(players_booked - $2, 0)" in conn.calls["fetchrow"][0][0]
