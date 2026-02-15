from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.schemas import BookTeeTimeRequest, CheckSlotCapacityRequest, ReservationType


def test_book_tee_time_rejects_non_uuid_slot_id() -> None:
    with pytest.raises(ValidationError):
        BookTeeTimeRequest(
            idempotency_key="idem-1",
            slot_id="3pm-slot-id",
            primary_contact={"name": "Sam Golfer"},
            players=2,
            num_holes=18,
            reservation_type=ReservationType.WALKING,
        )


def test_book_tee_time_allows_missing_phone_for_caller_id_fallback() -> None:
    request = BookTeeTimeRequest(
        idempotency_key="idem-2",
        slot_id="123e4567-e89b-12d3-a456-426614174000",
        primary_contact={"name": "Sam Golfer"},
        players=2,
        num_holes=18,
        reservation_type=ReservationType.WALKING,
    )

    assert request.primary_contact.phone_e164 == ""


def test_check_slot_capacity_rejects_non_uuid_slot_id() -> None:
    with pytest.raises(ValidationError):
        CheckSlotCapacityRequest(slot_id="3pm-slot-id", players=2)
