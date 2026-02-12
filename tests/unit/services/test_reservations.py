from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.app.services.reservations import ReservationStore

from ._fakes import FakeConnection, run


def reservation_row(
    *,
    confirmation_code: str = "RES-ABCDE1",
    status: str = "BOOKED",
    slot_id: str | None = None,
    players: int = 2,
    reservation_type: str = "WALKING",
    include_contact: bool = True,
) -> dict[str, object]:
    now = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc)
    row: dict[str, object] = {
        "reservation_id": uuid4(),
        "confirmation_code": confirmation_code,
        "status": status,
        "course_id": "course-1",
        "slot_id": slot_id or str(uuid4()),
        "date": "2026-03-01",
        "start_local": "09:00",
        "num_players": players,
        "num_holes": 18,
        "reservation_type": reservation_type,
        "created_at": now,
        "updated_at": now,
    }
    if include_contact:
        row["primary_contact_name"] = "Alex Caller"
        row["primary_contact_phone_e164"] = "+15551230000"
    return row


def test_find_by_confirmation_returns_reservation_with_contact() -> None:
    store = ReservationStore()
    conn = FakeConnection(fetchrow_results=[reservation_row()])

    result = run(store.find_by_confirmation(conn, "RES-ABCDE1"))

    assert result is not None
    assert result.confirmation_code == "RES-ABCDE1"
    assert result.primary_contact.name == "Alex Caller"
    assert result.primary_contact.phone_e164 == "+15551230000"
    assert "LEFT JOIN customers" in conn.calls["fetchrow"][0][0]


def test_find_by_confirmation_returns_none_when_missing() -> None:
    store = ReservationStore()
    conn = FakeConnection(fetchrow_results=[None])

    result = run(store.find_by_confirmation(conn, "RES-MISSING"))

    assert result is None


def test_create_requires_active_transaction() -> None:
    store = ReservationStore()
    conn = FakeConnection(in_transaction=False)

    with pytest.raises(RuntimeError, match="create reservation"):
        run(
            store.create(
                conn,
                idempotency_key="idem-1",
                slot_id=str(uuid4()),
                num_holes=18,
                reservation_type="WALKING",
                players=2,
                customer_id=str(uuid4()),
            )
        )


def test_create_returns_existing_reservation_for_idempotency_key() -> None:
    store = ReservationStore()
    conn = FakeConnection(fetchrow_results=[reservation_row()])

    result = run(
        store.create(
            conn,
            idempotency_key="idem-1",
            slot_id=str(uuid4()),
            num_holes=18,
            reservation_type="WALKING",
            players=2,
            customer_id=str(uuid4()),
        )
    )

    assert result.confirmation_code == "RES-ABCDE1"
    assert conn.calls["execute"] == []


def test_create_inserts_reservation_and_change_history(monkeypatch: pytest.MonkeyPatch) -> None:
    store = ReservationStore()
    generated_code = "RES-UNIT01"
    reservation_id = uuid4()

    monkeypatch.setattr(
        "backend.app.services.reservations.make_confirmation_code",
        lambda prefix: generated_code,
    )

    conn = FakeConnection(
        fetchrow_results=[
            None,
            {
                "reservation_id": reservation_id,
                "created_at": datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc),
                "updated_at": datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc),
            },
            reservation_row(confirmation_code=generated_code),
        ]
    )

    result = run(
        store.create(
            conn,
            idempotency_key="idem-2",
            slot_id=str(uuid4()),
            num_holes=18,
            reservation_type="WALKING",
            players=2,
            customer_id=str(uuid4()),
        )
    )

    assert result.confirmation_code == generated_code
    assert len(conn.calls["execute"]) == 1
    assert "INSERT INTO reservation_changes" in conn.calls["execute"][0][0]


def test_create_persists_call_id_on_reservation_and_change_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ReservationStore()
    generated_code = "RES-UNIT02"
    call_id = "call-123"

    monkeypatch.setattr(
        "backend.app.services.reservations.make_confirmation_code",
        lambda prefix: generated_code,
    )

    conn = FakeConnection(
        fetchrow_results=[
            None,
            {
                "reservation_id": uuid4(),
                "created_at": datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc),
                "updated_at": datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc),
            },
            reservation_row(confirmation_code=generated_code),
        ]
    )

    result = run(
        store.create(
            conn,
            idempotency_key="idem-call-id",
            call_id=call_id,
            slot_id=str(uuid4()),
            num_holes=18,
            reservation_type="WALKING",
            players=2,
            customer_id=str(uuid4()),
        )
    )

    assert result.confirmation_code == generated_code
    create_insert_args = conn.calls["fetchrow"][1][1]
    assert create_insert_args[-1] == call_id
    change_insert_args = conn.calls["execute"][0][1]
    assert change_insert_args[1] == call_id


def test_modify_requires_active_transaction() -> None:
    store = ReservationStore()
    conn = FakeConnection(in_transaction=False)

    with pytest.raises(RuntimeError, match="modify reservation"):
        run(
            store.modify(
                conn,
                confirmation_code="RES-ABCDE1",
                changes={"players": 3},
            )
        )


def test_modify_returns_none_when_reservation_not_found() -> None:
    store = ReservationStore()
    conn = FakeConnection(fetchrow_results=[None])

    result = run(
        store.modify(
            conn,
            confirmation_code="RES-MISSING",
            changes={"players": 3},
        )
    )

    assert result is None


def test_modify_updates_time_players_and_round_type() -> None:
    store = ReservationStore()
    current_slot_id = str(uuid4())
    target_slot_id = str(uuid4())

    conn = FakeConnection(
        fetchrow_results=[
            reservation_row(slot_id=current_slot_id, players=2, reservation_type="WALKING"),
            {"slot_id": current_slot_id, "course_id": "course-1"},
            {
                "slot_id": target_slot_id,
                "is_closed": False,
                "players_booked": 1,
                "capacity_players": 4,
            },
            {
                "slot_id": target_slot_id,
                "is_closed": False,
                "players_booked": 3,
                "capacity_players": 4,
            },
            reservation_row(
                slot_id=target_slot_id,
                players=3,
                reservation_type="RIDING",
            ),
        ],
        fetchval_results=["America/New_York"],
    )

    result = run(
        store.modify(
            conn,
            confirmation_code="RES-ABCDE1",
            changes={
                "start_local": "10:30",
                "players": 3,
                "reservation_type": "RIDING",
            },
        )
    )

    assert result is not None
    assert result.players == 3
    assert result.reservation_type.value == "RIDING"
    assert len(conn.calls["execute"]) == 7
    assert "INSERT INTO reservation_changes" in conn.calls["execute"][-1][0]


def test_modify_propagates_call_id_to_reservation_updates_and_change_log() -> None:
    store = ReservationStore()
    current_slot_id = str(uuid4())
    call_id = "call-456"

    conn = FakeConnection(
        fetchrow_results=[
            reservation_row(slot_id=current_slot_id, players=2, reservation_type="WALKING"),
            {"slot_id": current_slot_id, "course_id": "course-1"},
            {
                "slot_id": current_slot_id,
                "is_closed": False,
                "players_booked": 1,
                "capacity_players": 4,
            },
            reservation_row(slot_id=current_slot_id, players=3, reservation_type="WALKING"),
        ]
    )

    result = run(
        store.modify(
            conn,
            confirmation_code="RES-ABCDE1",
            changes={"players": 3},
            call_id=call_id,
        )
    )

    assert result is not None
    reservation_update_args = next(
        args
        for sql, args in conn.calls["execute"]
        if "UPDATE reservations" in sql and "SET num_players = $1" in sql
    )
    assert reservation_update_args[-1] == call_id
    change_insert_args = next(
        args
        for sql, args in conn.calls["execute"]
        if "INSERT INTO reservation_changes" in sql
    )
    assert change_insert_args[1] == call_id


def test_cancel_requires_active_transaction() -> None:
    store = ReservationStore()
    conn = FakeConnection(in_transaction=False)

    with pytest.raises(RuntimeError, match="cancel reservation"):
        run(store.cancel(conn, "RES-ABCDE1", "idem-cancel"))


def test_cancel_returns_none_when_reservation_not_found() -> None:
    store = ReservationStore()
    conn = FakeConnection(fetchrow_results=[None])

    result = run(store.cancel(conn, "RES-MISSING", "idem-cancel"))

    assert result is None


def test_cancel_is_noop_when_already_cancelled() -> None:
    store = ReservationStore()
    conn = FakeConnection(
        fetchrow_results=[reservation_row(status="CANCELLED")],
    )

    result = run(store.cancel(conn, "RES-ABCDE1", "idem-cancel"))

    assert result is not None
    assert result.status.value == "CANCELLED"
    assert conn.calls["fetchval"] == []
    assert conn.calls["execute"] == []


def test_cancel_updates_reservation_and_writes_change_record() -> None:
    store = ReservationStore()
    reservation_id = uuid4()
    conn = FakeConnection(
        fetchrow_results=[
            reservation_row(status="BOOKED"),
            reservation_row(status="CANCELLED"),
        ],
        fetchval_results=[reservation_id],
    )

    result = run(store.cancel(conn, "RES-ABCDE1", "idem-cancel"))

    assert result is not None
    assert result.status.value == "CANCELLED"
    assert len(conn.calls["execute"]) == 1
    assert "INSERT INTO reservation_changes" in conn.calls["execute"][0][0]
    assert conn.calls["execute"][0][1][2] == "idem-cancel"


def test_cancel_propagates_call_id_to_reservation_and_change_log() -> None:
    store = ReservationStore()
    reservation_id = uuid4()
    call_id = "call-789"
    conn = FakeConnection(
        fetchrow_results=[
            reservation_row(status="BOOKED"),
            reservation_row(status="CANCELLED"),
        ],
        fetchval_results=[reservation_id],
    )

    result = run(
        store.cancel(
            conn,
            "RES-ABCDE1",
            "idem-cancel-2",
            call_id,
        )
    )

    assert result is not None
    cancel_update_args = conn.calls["fetchval"][0][1]
    assert cancel_update_args[1] == call_id
    change_insert_args = conn.calls["execute"][0][1]
    assert change_insert_args[1] == call_id


def test_row_to_reservation_uses_empty_contact_defaults() -> None:
    store = ReservationStore()
    row = reservation_row(include_contact=False)

    result = store._row_to_reservation(row)

    assert result.primary_contact.name == ""
    assert result.primary_contact.phone_e164 == ""
