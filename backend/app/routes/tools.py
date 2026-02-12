from __future__ import annotations

"""Tool API routes for tee time reservation management.

The goal of this module is to keep endpoint handlers thin and move repeatable
logic (auth, write guards, shared DB lookups/normalization) into helpers.
"""

from datetime import datetime
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Header

from shared import schemas
from ..config import settings
from ..db import get_conn, transaction
from ..services.inventory import InventoryStore
from ..services.reservations import ReservationStore

############################### GLOBALS ###############################

router = APIRouter(prefix="/v1/tools")
inventory_store = InventoryStore()
reservation_store = ReservationStore()
SEARCH_FRESHNESS_TTL_SECONDS = 300

############################### HELPERS ###############################

def require_auth(authorization: str | None = Header(default=None)) -> None:
    """Validates bearer-token authentication for tool endpoints.

    Args:
        authorization: Raw Authorization header value.

    Raises:
        HTTPException: If the caller token does not match the backend API key.
    """
    if authorization != f"Bearer {settings.BACKEND_API_KEY}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def require_writable_db() -> None:
    """Guards write operations when the backend is configured as read-only.

    Raises:
        HTTPException: If write operations are currently disabled.
    """
    if settings.DB_READ_ONLY:
        raise HTTPException(status_code=403, detail="DB is in read-only mode")


def build_freshness_payload() -> dict[str, Any]:
    """Builds response metadata used by clients to reason about staleness.

    Returns:
        A payload containing generation time and time-to-live settings.
    """
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "ttl_seconds": SEARCH_FRESHNESS_TTL_SECONDS,
    }


def normalize_modify_changes(request: schemas.ModifyReservationRequest) -> dict[str, Any]:
    """Normalizes modify-reservation fields before persistence.

    Reservation type is normalized to uppercase so downstream logic can rely on
    a single representation regardless of caller casing.

    Args:
        request: Validated API payload for a reservation modification.

    Returns:
        A normalized dictionary of requested changes.
    """
    normalized_changes = request.changes.model_dump()
    reservation_type = normalized_changes.get("reservation_type")
    if reservation_type:
        normalized_changes["reservation_type"] = str(reservation_type).upper()
    return normalized_changes


async def fetch_slot_by_id(conn: asyncpg.Connection, slot_id: str) -> asyncpg.Record | None:
    """Fetches a tee-time slot by identifier.

    Args:
        conn: Active database connection.
        slot_id: Target slot identifier.

    Returns:
        Matching slot row if found, otherwise ``None``.
    """
    return await conn.fetchrow(
        "SELECT * FROM tee_time_slots WHERE slot_id = $1",
        slot_id,
    )


async def get_reservation_or_404(
    conn: asyncpg.Connection, confirmation_code: str
) -> schemas.Reservation:
    """Fetches a reservation and enforces consistent not-found handling.

    Args:
        conn: Active database connection.
        confirmation_code: Reservation confirmation code from the caller.

    Returns:
        The matching reservation.

    Raises:
        HTTPException: If no reservation exists for the confirmation code.
    """
    reservation = await reservation_store.find_by_confirmation(conn, confirmation_code)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return reservation


def slot_has_capacity(slot: dict[str, Any] | asyncpg.Record, players: int) -> bool:
    """Evaluates whether a slot can accept additional players.

    Args:
        slot: Slot data containing capacity, booked count, and open/closed state.
        players: Number of players requested for this operation.

    Returns:
        ``True`` when the slot is open and has enough remaining capacity.
    """
    return not slot["is_closed"] and slot["players_booked"] + players <= slot["capacity_players"]


############################### ROUTES ###############################

## Endpoint: Search Tee Times
## Usage: Search the current tee time inventory for available tee times and return options.
@router.post("/search-tee-times", response_model=schemas.SearchTeeTimesResponse)
async def search_tee_times(
    request: schemas.SearchTeeTimesRequest, _auth: None = Depends(require_auth)
):
    # Read-only flow: query availability, then attach freshness metadata.
    async with get_conn() as conn:
        options = await inventory_store.search(conn, request)
    return schemas.SearchTeeTimesResponse(
        course_id=request.course_id,
        date=request.date,
        timezone="America/New_York",
        options=options,
        freshness=build_freshness_payload(),
    )


## Endpoint: Book Tee Time
## Usage: Reserve a selected slot for a caller and return reservation details.
@router.post("/book-tee-time", response_model=schemas.BookTeeTimeResponse)
async def book_tee_time(
    request: schemas.BookTeeTimeRequest, _auth: None = Depends(require_auth)
):
    # Booking mutates inventory and reservation state, so writes must be enabled.
    require_writable_db()

    async with transaction() as conn:
        # Lock the slot row first so capacity checks and inventory updates are atomic.
        slot = await inventory_store.get_slot_for_update(conn, request.slot_id)
        if not slot:
            raise HTTPException(status_code=404, detail="slot_id not found")
        if not slot_has_capacity(slot, request.players):
            raise HTTPException(status_code=409, detail="Slot no longer available")

        updated_slot = await inventory_store.increment_players_booked(
            conn, request.slot_id, request.players
        )
        if not updated_slot:
            raise HTTPException(status_code=409, detail="Slot no longer available")

        # Upsert customer so repeated callers keep a single identity record.
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

        # Persist reservation and reservation-change history in the same transaction.
        reservation = await reservation_store.create(
            conn,
            idempotency_key=request.idempotency_key,
            call_id=request.call_id,
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


## Endpoint: Modify Reservation
## Usage: Apply caller-requested changes to an existing reservation.
@router.post("/modify-reservation", response_model=schemas.ModifyReservationResponse)
async def modify_reservation(
    request: schemas.ModifyReservationRequest, _auth: None = Depends(require_auth)
):
    # Modifications are writes; enforce the same read-only gate as booking/cancel.
    require_writable_db()
    normalized_changes = normalize_modify_changes(request)

    async with transaction() as conn:
        updated = await reservation_store.modify(
            conn,
            confirmation_code=request.confirmation_code,
            changes=normalized_changes,
            call_id=request.call_id,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Reservation not found")

    return schemas.ModifyReservationResponse(
        confirmation_code=updated.confirmation_code,
        reservation=updated,
    )


## Endpoint: Cancel Reservation
## Usage: Cancel an existing reservation using its confirmation code.
@router.post("/cancel-reservation", response_model=schemas.CancelReservationResponse)
async def cancel_reservation(
    request: schemas.CancelReservationRequest, _auth: None = Depends(require_auth)
):
    # Cancellation mutates reservation status and audit history.
    require_writable_db()

    async with transaction() as conn:
        updated = await reservation_store.cancel(
            conn,
            request.confirmation_code,
            request.idempotency_key,
            request.call_id,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Reservation not found")

    return schemas.CancelReservationResponse(
        confirmation_code=updated.confirmation_code,
        status=updated.status,
        cancelled_at=updated.cancelled_at,
        policy={"fee_applied": False, "message": "Cancelled successfully."},
    )


## Endpoint: Get Reservation Details
## Usage: Fetch the current reservation state for a confirmation code.
@router.post(
    "/get-reservation-details",
    response_model=schemas.GetReservationDetailsResponse,
)
async def get_reservation_details(
    request: schemas.GetReservationDetailsRequest, _auth: None = Depends(require_auth)
):
    # Read-only lookup with consistent 404 behavior.
    async with get_conn() as conn:
        reservation = await get_reservation_or_404(conn, request.confirmation_code)

    return schemas.GetReservationDetailsResponse(reservation=reservation)


## Endpoint: Quote Reservation Change
## Usage: Evaluate whether a proposed change is currently feasible before applying it.
@router.post(
    "/quote-reservation-change",
    response_model=schemas.QuoteReservationChangeResponse,
)
async def quote_reservation_change(
    request: schemas.QuoteReservationChangeRequest, _auth: None = Depends(require_auth)
):
    # Quote mode never mutates data; it only evaluates feasibility.
    async with get_conn() as conn:
        current = await get_reservation_or_404(conn, request.confirmation_code)

        capacity_ok = True
        reason = None
        target_start_ts = None

        # If a new slot is requested, evaluate open/closed and capacity constraints.
        if request.new_slot_id:
            slot = await fetch_slot_by_id(conn, request.new_slot_id)
            if not slot:
                capacity_ok = False
                reason = "Requested slot unavailable"
            else:
                desired_players = request.new_players or current.players
                if not slot_has_capacity(slot, desired_players):
                    capacity_ok = False
                    reason = (
                        "Requested slot unavailable"
                        if slot["is_closed"]
                        else "Not enough capacity"
                    )
                else:
                    target_start_ts = slot["start_ts"].isoformat()

    return schemas.QuoteReservationChangeResponse(
        can_change=capacity_ok,
        reason=reason,
        capacity_ok=capacity_ok,
        target_start_ts=target_start_ts,
    )


## Endpoint: Check Slot Capacity
## Usage: Check if a specific slot can support the requested player count.
@router.post(
    "/check-slot-capacity",
    response_model=schemas.CheckSlotCapacityResponse,
)
async def check_slot_capacity(
    request: schemas.CheckSlotCapacityRequest, _auth: None = Depends(require_auth)
):
    # Simple capacity probe for callers that already know the slot identifier.
    async with get_conn() as conn:
        slot = await fetch_slot_by_id(conn, request.slot_id)
        if not slot:
            raise HTTPException(status_code=404, detail="slot_id not found")

    available = slot_has_capacity(slot, request.players)

    return schemas.CheckSlotCapacityResponse(
        available=available,
        capacity_players=slot["capacity_players"],
        players_booked=slot["players_booked"],
    )


## Endpoint: Send SMS Confirmation
## Usage: Return a confirmation payload for SMS notification dispatch.
@router.post(
    "/send-sms-confirmation",
    response_model=schemas.SendSmsConfirmationResponse,
)
async def send_sms_confirmation(
    request: schemas.SendSmsConfirmationRequest, _auth: None = Depends(require_auth)
):
    # Placeholder endpoint: currently reports queuing intent without external SMS I/O.
    return schemas.SendSmsConfirmationResponse(
        status="queued",
        confirmation_code=request.confirmation_code,
        phone_e164=request.phone_e164,
    )
