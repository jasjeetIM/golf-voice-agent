from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class Money(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    amount_total: float = Field(ge=0)
    amount_per_player: float = Field(ge=0)


class ReservationType(str, Enum):
    WALKING = "WALKING"
    RIDING = "RIDING"


class ReservationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class PrimaryContact(BaseModel):
    name: str
    phone_e164: str


class Reservation(BaseModel):
    reservation_id: str
    confirmation_code: str
    status: ReservationStatus
    course_id: str
    slot_id: str
    date: str
    start_local: str
    players: int = Field(ge=1, le=4)
    num_holes: Literal[9, 18]
    reservation_type: ReservationType
    primary_contact: PrimaryContact
    created_at: str
    updated_at: Optional[str] = None
    cancelled_at: Optional[str] = None

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        # YYYY-MM-DD basic validation
        if len(value) != 10 or value[4] != "-" or value[7] != "-":
            raise ValueError("Invalid date format")
        return value

    @field_validator("start_local")
    @classmethod
    def validate_start_local(cls, value: str) -> str:
        if len(value) != 5 or value[2] != ":":
            raise ValueError("Expected HH:MM")
        return value


class TimeWindow(BaseModel):
    start_local: str
    end_local: str

    @field_validator("start_local", "end_local")
    @classmethod
    def validate_time(cls, value: str) -> str:
        if len(value) != 5 or value[2] != ":":
            raise ValueError("Expected HH:MM")
        return value

    @model_validator(mode="after")
    def validate_window(self) -> "TimeWindow":
        if self.start_local >= self.end_local:
            raise ValueError("start_local must be before end_local")
        return self


class TeeTimeOption(BaseModel):
    slot_id: str
    start_local: str
    duration_min: int
    players_allowed: list[int]
    price: Money
    constraints: dict


class SearchTeeTimesRequest(BaseModel):
    call_id: Optional[str] = None
    course_id: str
    date: str
    time_window: TimeWindow
    players: int = Field(ge=1, le=4)
    holes: Literal[9, 18] = 18
    reservation_type: ReservationType
    max_results: int = Field(ge=1, le=10, default=5)


class SearchTeeTimesResponse(BaseModel):
    course_id: str
    date: str
    timezone: str
    options: list[TeeTimeOption]
    freshness: dict


class BookTeeTimeRequest(BaseModel):
    idempotency_key: str
    call_id: Optional[str] = None
    slot_id: str
    primary_contact: PrimaryContact
    players: int = Field(ge=1, le=4)
    num_holes: Literal[9, 18]
    reservation_type: ReservationType


class BookTeeTimeResponse(BaseModel):
    confirmation_code: str
    reservation: Reservation


class ModifyReservationRequest(BaseModel):
    confirmation_code: str
    idempotency_key: str
    call_id: Optional[str] = None
    class Changes(BaseModel):
        start_local: Optional[str] = None
        players: Optional[int] = Field(default=None, ge=1, le=4)
        reservation_type: Optional[str] = None

        @model_validator(mode="after")
        def validate_changes(self) -> "ModifyReservationRequest.Changes":
            if (
                self.start_local is None
                and self.players is None
                and self.reservation_type is None
            ):
                raise ValueError("At least one change is required")
            return self

    changes: Changes


class ModifyReservationResponse(BaseModel):
    confirmation_code: str
    reservation: Reservation


class CancelReservationRequest(BaseModel):
    confirmation_code: str
    idempotency_key: str
    call_id: Optional[str] = None


class CancelReservationResponse(BaseModel):
    confirmation_code: str
    status: ReservationStatus
    cancelled_at: Optional[str] = None
    policy: Optional[dict] = None


class SendSmsConfirmationRequest(BaseModel):
    call_id: Optional[str] = None
    confirmation_code: str
    phone_e164: str


class SendSmsConfirmationResponse(BaseModel):
    status: Literal["queued", "sent", "failed"] = "queued"
    confirmation_code: str
    phone_e164: str


class GetReservationDetailsRequest(BaseModel):
    call_id: Optional[str] = None
    confirmation_code: str


class GetReservationDetailsResponse(BaseModel):
    reservation: Reservation


class QuoteReservationChangeRequest(BaseModel):
    call_id: Optional[str] = None
    confirmation_code: str
    new_slot_id: Optional[str] = None
    new_players: Optional[int] = Field(default=None, ge=1, le=4)
    new_reservation_type: Optional[str] = None


class QuoteReservationChangeResponse(BaseModel):
    can_change: bool
    reason: Optional[str] = None
    capacity_ok: Optional[bool] = None
    target_start_ts: Optional[str] = None


class CheckSlotCapacityRequest(BaseModel):
    call_id: Optional[str] = None
    slot_id: str
    players: int = Field(ge=1, le=4)


class CheckSlotCapacityResponse(BaseModel):
    available: bool
    capacity_players: int
    players_booked: int
