from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Header

from shared import schemas
from ..config import settings
from ..db import get_conn, transaction
from ..services.inventory import InventoryStore
from ..services.reservations import ReservationStore

router = APIRouter(prefix="/v1/tools")

inventory = InventoryStore()
reservations = ReservationStore()


def require_auth(authorization: str | None = Header(default=None)) -> None:
    if authorization != f"Bearer {settings.BACKEND_API_KEY}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/search-tee-times", response_model=schemas.SearchTeeTimesResponse)
async def search_tee_times(
    request: schemas.SearchTeeTimesRequest, _auth: None = Depends(require_auth)
):
    async with get_conn() as conn:
        options = await inventory.search(conn, request)
    return schemas.SearchTeeTimesResponse(
        course_id=request.course_id,
        date=request.date,
        timezone="America/New_York",
        options=options,
        freshness={"generated_at": datetime.utcnow().isoformat(), "ttl_seconds": 300},
    )


@router.post("/book-tee-time", response_model=schemas.BookTeeTimeResponse)
async def book_tee_time(
    request: schemas.BookTeeTimeRequest, _auth: None = Depends(require_auth)
):
    if settings.DB_READ_ONLY:
        raise HTTPException(status_code=403, detail="DB is in read-only mode")

    async with transaction() as conn:
        slot = await inventory.get_slot_for_update(conn, request.slot_id)
        if not slot:
            raise HTTPException(status_code=404, detail="slot_id not found")
        if slot["players_booked"] + request.players > slot["capacity_players"] or slot["is_closed"]:
            raise HTTPException(status_code=409, detail="Slot no longer available")

        updated_slot = await inventory.increment_players_booked(
            conn, request.slot_id, request.players
        )
        if not updated_slot:
            raise HTTPException(status_code=409, detail="Slot no longer available")

        customer_row = await conn.fetchrow(
            """
            INSERT INTO customers (phone_e164, full_name)
            VALUES ($1,$2)
            ON CONFLICT (phone_e164) DO UPDATE SET full_name = EXCLUDED.full_name
            RETURNING customer_id
            """,
            request.primary_contact.phone_e164,
            request.primary_contact.name,
        )
        customer_id = customer_row["customer_id"]

        reservation = await reservations.create(
            conn,
            idempotency_key=request.idempotency_key,
            slot_id=request.slot_id,
            num_holes=request.num_holes,
            reservation_type=request.reservation_type,
            players=request.players,
            customer_id=str(customer_id),
        )

    return schemas.BookTeeTimeResponse(
        confirmation_code=reservation.confirmation_code,
        reservation=reservation,
    )


@router.post("/modify-reservation", response_model=schemas.ModifyReservationResponse)
async def modify_reservation(
    request: schemas.ModifyReservationRequest, _auth: None = Depends(require_auth)
):
    if settings.DB_READ_ONLY:
        raise HTTPException(status_code=403, detail="DB is in read-only mode")

    normalized_changes = request.changes.model_dump()
    if "reservation_type" in normalized_changes and normalized_changes["reservation_type"]:
        normalized_changes["reservation_type"] = str(normalized_changes["reservation_type"]).upper()

    async with transaction() as conn:
        updated = await reservations.modify(
            conn,
            confirmation_code=request.confirmation_code,
            changes=normalized_changes,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Reservation not found")

    return schemas.ModifyReservationResponse(
        confirmation_code=updated.confirmation_code,
        reservation=updated,
    )


@router.post("/cancel-reservation", response_model=schemas.CancelReservationResponse)
async def cancel_reservation(
    request: schemas.CancelReservationRequest, _auth: None = Depends(require_auth)
):
    if settings.DB_READ_ONLY:
        raise HTTPException(status_code=403, detail="DB is in read-only mode")

    async with transaction() as conn:
        updated = await reservations.cancel(conn, request.confirmation_code)
        if not updated:
            raise HTTPException(status_code=404, detail="Reservation not found")

    return schemas.CancelReservationResponse(
        confirmation_code=updated.confirmation_code,
        status=updated.status,
        cancelled_at=updated.cancelled_at,
        policy={"fee_applied": False, "message": "Cancelled successfully."},
    )


@router.post("/get-reservation-details", response_model=schemas.GetReservationDetailsResponse)
async def get_reservation_details(
    request: schemas.GetReservationDetailsRequest, _auth: None = Depends(require_auth)
):
    async with get_conn() as conn:
        reservation = await reservations.find_by_confirmation(conn, request.confirmation_code)
        if not reservation:
            raise HTTPException(status_code=404, detail="Reservation not found")

    return schemas.GetReservationDetailsResponse(reservation=reservation)


@router.post("/quote-reservation-change", response_model=schemas.QuoteReservationChangeResponse)
async def quote_reservation_change(
    request: schemas.QuoteReservationChangeRequest, _auth: None = Depends(require_auth)
):
    async with get_conn() as conn:
        current = await reservations.find_by_confirmation(conn, request.confirmation_code)
        if not current:
            raise HTTPException(status_code=404, detail="Reservation not found")

        capacity_ok = True
        reason = None
        target_start_ts = None

        if request.new_slot_id:
            slot = await conn.fetchrow(
                "SELECT * FROM tee_time_slots WHERE slot_id = $1",
                request.new_slot_id,
            )
            if not slot or slot["is_closed"]:
                capacity_ok = False
                reason = "Requested slot unavailable"
            else:
                desired_players = request.new_players or current.players
                if slot["players_booked"] + desired_players > slot["capacity_players"]:
                    capacity_ok = False
                    reason = "Not enough capacity"
                else:
                    target_start_ts = slot["start_ts"].isoformat()

    return schemas.QuoteReservationChangeResponse(
        can_change=capacity_ok,
        reason=reason,
        capacity_ok=capacity_ok,
        target_start_ts=target_start_ts,
    )


@router.post("/check-slot-capacity", response_model=schemas.CheckSlotCapacityResponse)
async def check_slot_capacity(
    request: schemas.CheckSlotCapacityRequest, _auth: None = Depends(require_auth)
):
    async with get_conn() as conn:
        slot = await conn.fetchrow(
            "SELECT * FROM tee_time_slots WHERE slot_id = $1",
            request.slot_id,
        )
        if not slot:
            raise HTTPException(status_code=404, detail="slot_id not found")

    available = (
        not slot["is_closed"]
        and slot["players_booked"] + request.players <= slot["capacity_players"]
    )

    return schemas.CheckSlotCapacityResponse(
        available=available,
        capacity_players=slot["capacity_players"],
        players_booked=slot["players_booked"],
    )


@router.post("/send-sms-confirmation", response_model=schemas.SendSmsConfirmationResponse)
async def send_sms_confirmation(
    request: schemas.SendSmsConfirmationRequest, _auth: None = Depends(require_auth)
):
    return schemas.SendSmsConfirmationResponse(
        status="queued",
        confirmation_code=request.confirmation_code,
        phone_e164=request.phone_e164,
    )
