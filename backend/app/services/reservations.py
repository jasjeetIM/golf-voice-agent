"""Reservation data access for tee time management."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Literal
from zoneinfo import ZoneInfo

import json
import asyncpg

from shared.schemas import Reservation
from .confirmation_code import make_confirmation_code

_LOGGER = logging.getLogger(__name__)


class ReservationStore:
    """Persistence operations for reservation create/read/update/cancel flows."""

    @staticmethod
    def _require_active_transaction(conn: asyncpg.Connection, operation: str) -> None:
        """Ensures write operations execute inside an active DB transaction.

        Args:
            conn: Active database connection.
            operation: Human-readable operation label for error messages.

        Raises:
            RuntimeError: If no transaction is active on the connection.
        """
        _LOGGER.debug(
            "ReservationStore._require_active_transaction() called.",
            extra={"operation": operation, "in_transaction": conn.is_in_transaction()},
        )
        if not conn.is_in_transaction():
            raise RuntimeError(f"{operation} must run inside a database transaction")

    async def find_by_confirmation(
        self, conn: asyncpg.Connection, confirmation_code: str
    ) -> Reservation | None:
        """Looks up a reservation by confirmation code.

        Args:
            conn: Active database connection.
            confirmation_code: Caller-facing confirmation code.

        Returns:
            Reservation model when found, otherwise ``None``.
        """
        _LOGGER.debug(
            "ReservationStore.find_by_confirmation() called.",
            extra={"confirmation_code": confirmation_code},
        )
        row = await conn.fetchrow(
            """
            SELECT r.*, t.course_id, t.start_ts,
                   to_char(t.start_ts, 'HH24:MI') AS start_local,
                   to_char(t.start_ts, 'YYYY-MM-DD') AS date,
                   c.full_name AS primary_contact_name,
                   c.phone_e164 AS primary_contact_phone_e164
            FROM reservations r
            JOIN tee_time_slots t ON r.slot_id = t.slot_id
            LEFT JOIN customers c ON r.customer_id = c.customer_id
            WHERE r.confirmation_code = $1
            """,
            confirmation_code,
        )
        _LOGGER.debug(
            "ReservationStore.find_by_confirmation() DB read complete.",
            extra={"confirmation_code": confirmation_code, "found": row is not None},
        )
        if not row:
            return None
        reservation = self._row_to_reservation(dict(row))
        _LOGGER.debug(
            "ReservationStore.find_by_confirmation() mapped reservation.",
            extra={
                "confirmation_code": confirmation_code,
                "reservation_id": reservation.reservation_id,
                "status": reservation.status,
                "slot_id": reservation.slot_id,
                "players": reservation.players,
            },
        )
        return reservation

    async def create(
        self,
        conn: asyncpg.Connection,
        *,
        idempotency_key: str,
        call_id: str | None = None,
        slot_id: str,
        num_holes: Literal[9, 18],
        reservation_type: Literal["WALKING", "RIDING"],
        players: int,
        customer_id: str,
    ) -> Reservation:
        """Creates a reservation and writes corresponding change history.

        Args:
            conn: Active database connection.
            idempotency_key: Key that deduplicates retried create requests.
            call_id: Optional call identifier associated with this mutation.
            slot_id: Selected tee-time slot identifier.
            num_holes: Number of holes requested.
            reservation_type: Walking/riding preference.
            players: Number of players on the reservation.
            customer_id: Existing or upserted customer identifier.

        Returns:
            The created reservation, or the existing reservation for duplicate
            idempotency keys.

        Raises:
            RuntimeError: If called outside an active database transaction.
        """
        _LOGGER.debug(
            "ReservationStore.create() called.",
            extra={
                "idempotency_key": idempotency_key,
                "call_id": call_id,
                "slot_id": slot_id,
                "num_holes": num_holes,
                "reservation_type": reservation_type,
                "players": players,
                "customer_id": customer_id,
            },
        )
        self._require_active_transaction(conn, "create reservation")

        # Idempotent create: if this key was already applied, return that result.
        existing = await conn.fetchrow(
            """
            SELECT rc.change_id, r.*, t.course_id, t.start_ts,
                   to_char(t.start_ts, 'HH24:MI') AS start_local,
                   to_char(t.start_ts, 'YYYY-MM-DD') AS date,
                   c.full_name AS primary_contact_name,
                   c.phone_e164 AS primary_contact_phone_e164
            FROM reservation_changes rc
            JOIN reservations r ON rc.reservation_id = r.reservation_id
            JOIN tee_time_slots t ON r.slot_id = t.slot_id
            LEFT JOIN customers c ON r.customer_id = c.customer_id
            WHERE rc.idempotency_key = $1
            """,
            idempotency_key,
        )
        _LOGGER.debug(
            "ReservationStore.create() idempotency check complete.",
            extra={"idempotency_key": idempotency_key, "existing_change_found": existing is not None},
        )
        if existing:
            reservation = self._row_to_reservation(dict(existing))
            _LOGGER.debug(
                "ReservationStore.create() returning existing reservation for idempotency key.",
                extra={
                    "idempotency_key": idempotency_key,
                    "reservation_id": reservation.reservation_id,
                    "confirmation_code": reservation.confirmation_code,
                },
            )
            return reservation

        # Generate a caller-friendly confirmation code and persist reservation.
        confirmation_code = make_confirmation_code("RES")
        _LOGGER.debug(
            "ReservationStore.create() generated confirmation code.",
            extra={"confirmation_code": confirmation_code},
        )
        res_row = await conn.fetchrow(
            """
            INSERT INTO reservations
            (
                confirmation_code,
                slot_id,
                customer_id,
                num_holes,
                reservation_type,
                num_players,
                status,
                created_by_call_id,
                updated_by_call_id
            )
            VALUES ($1,$2,$3,$4,$5,$6,'BOOKED',$7,$7)
            RETURNING reservation_id, created_at, updated_at
            """,
            confirmation_code,
            slot_id,
            customer_id,
            num_holes,
            reservation_type,
            players,
            call_id,
        )
        reservation_id = res_row["reservation_id"]
        _LOGGER.debug(
            "ReservationStore.create() inserted reservation row.",
            extra={
                "reservation_id": str(reservation_id),
                "confirmation_code": confirmation_code,
                "created_at": res_row["created_at"].isoformat() if res_row["created_at"] else None,
                "updated_at": res_row["updated_at"].isoformat() if res_row["updated_at"] else None,
            },
        )

        # Record create audit event keyed by idempotency token.
        await conn.execute(
            """
            INSERT INTO reservation_changes
            (reservation_id, change_type, call_id, idempotency_key, after_json)
            VALUES ($1,'CREATE',$2,$3,$4)
            """,
            reservation_id,
            call_id,
            idempotency_key,
            json.dumps({"confirmation_code": confirmation_code}),
        )
        _LOGGER.debug(
            "ReservationStore.create() inserted reservation_changes CREATE row.",
            extra={
                "reservation_id": str(reservation_id),
                "idempotency_key": idempotency_key,
                "call_id": call_id,
                "change_type": "CREATE",
            },
        )

        # Re-read joined row so API returns a full normalized reservation payload.
        row = await conn.fetchrow(
            """
            SELECT r.*, t.course_id, t.start_ts,
                   to_char(t.start_ts, 'HH24:MI') AS start_local,
                   to_char(t.start_ts, 'YYYY-MM-DD') AS date,
                   c.full_name AS primary_contact_name,
                   c.phone_e164 AS primary_contact_phone_e164
            FROM reservations r
            JOIN tee_time_slots t ON r.slot_id = t.slot_id
            LEFT JOIN customers c ON r.customer_id = c.customer_id
            WHERE r.reservation_id = $1
            """,
            reservation_id,
        )
        _LOGGER.debug(
            "ReservationStore.create() fetched joined reservation row.",
            extra={"reservation_id": str(reservation_id), "row_found": row is not None},
        )
        reservation = self._row_to_reservation(dict(row))
        _LOGGER.debug(
            "ReservationStore.create() returning reservation model.",
            extra={
                "reservation_id": reservation.reservation_id,
                "confirmation_code": reservation.confirmation_code,
                "status": reservation.status,
                "slot_id": reservation.slot_id,
                "players": reservation.players,
            },
        )
        return reservation

    async def modify(
        self,
        conn: asyncpg.Connection,
        *,
        confirmation_code: str,
        idempotency_key: str | None = None,
        changes: dict[str, Any],
        call_id: str | None = None,
    ) -> Reservation | None:
        """Modifies reservation time/player-count/round-type fields.

        Args:
            conn: Active database connection.
            confirmation_code: Reservation to update.
            idempotency_key: Optional key used to deduplicate retried modifies.
            changes: Normalized change-set from the API layer.
            call_id: Optional call identifier associated with this mutation.

        Returns:
            Updated reservation model, or ``None`` if no reservation exists.

        Raises:
            RuntimeError: If called outside a transaction or if target slot state
                makes the requested change invalid.
        """
        _LOGGER.debug(
            "ReservationStore.modify() called.",
            extra={
                "confirmation_code": confirmation_code,
                "idempotency_key": idempotency_key,
                "changes": changes,
                "call_id": call_id,
            },
        )
        self._require_active_transaction(conn, "modify reservation")

        existing = await self.find_by_confirmation(conn, confirmation_code)
        if not existing:
            _LOGGER.debug(
                "ReservationStore.modify() target reservation not found.",
                extra={"confirmation_code": confirmation_code},
            )
            return None
        _LOGGER.debug(
            "ReservationStore.modify() loaded current reservation.",
            extra={
                "confirmation_code": confirmation_code,
                "reservation_id": existing.reservation_id,
                "slot_id": existing.slot_id,
                "players": existing.players,
            },
        )

        # Idempotent modify: if this key has already been applied to the same
        # reservation, return the current persisted reservation state.
        if idempotency_key:
            prior = await conn.fetchval(
                """
                SELECT 1
                FROM reservation_changes rc
                JOIN reservations r ON r.reservation_id = rc.reservation_id
                WHERE rc.idempotency_key = $1
                  AND r.confirmation_code = $2
                """,
                idempotency_key,
                confirmation_code,
            )
            _LOGGER.debug(
                "ReservationStore.modify() idempotency check complete.",
                extra={
                    "idempotency_key": idempotency_key,
                    "confirmation_code": confirmation_code,
                    "prior_change_found": bool(prior),
                },
            )
            if prior:
                reservation = await self.find_by_confirmation(conn, confirmation_code)
                _LOGGER.debug(
                    "ReservationStore.modify() returning existing reservation for idempotency key.",
                    extra={
                        "idempotency_key": idempotency_key,
                        "confirmation_code": confirmation_code,
                        "reservation_id": reservation.reservation_id if reservation else None,
                    },
                )
                return reservation

        # Convert local time change requests into UTC timestamps for slot matching.
        if changes.get("start_local") and not changes.get("start_ts"):
            tz = await conn.fetchval(
                "SELECT timezone FROM courses WHERE course_id = $1",
                existing.course_id,
            )
            _LOGGER.debug(
                "ReservationStore.modify() fetched course timezone for start_local conversion.",
                extra={"course_id": existing.course_id, "timezone": tz},
            )
            if tz:
                local_dt = datetime.fromisoformat(f"{existing.date}T{changes['start_local']}:00")
                local_dt = local_dt.replace(tzinfo=ZoneInfo(tz))
                changes["start_ts"] = local_dt.astimezone(timezone.utc).isoformat()
                _LOGGER.debug(
                    "ReservationStore.modify() converted start_local to UTC timestamp.",
                    extra={
                        "confirmation_code": confirmation_code,
                        "start_local": changes.get("start_local"),
                        "start_ts": changes.get("start_ts"),
                    },
                )

        # Lock the current slot so later capacity updates remain consistent.
        current_slot = await conn.fetchrow(
            "SELECT * FROM tee_time_slots WHERE slot_id = $1 FOR UPDATE",
            existing.slot_id,
        )
        _LOGGER.debug(
            "ReservationStore.modify() locked current slot row.",
            extra={"slot_id": existing.slot_id, "found": current_slot is not None},
        )
        if not current_slot:
            raise RuntimeError("Current slot not found")

        active_slot_id = current_slot["slot_id"]
        current_players = existing.players

        # Time change flow: lock target slot, validate capacity, move player load.
        if changes.get("start_ts"):
            target = await conn.fetchrow(
                """
                SELECT * FROM tee_time_slots
                WHERE course_id = $1 AND start_ts = $2 FOR UPDATE
                """,
                current_slot["course_id"],
                changes["start_ts"],
            )
            _LOGGER.debug(
                "ReservationStore.modify() looked up target slot for time change.",
                extra={
                    "course_id": current_slot["course_id"],
                    "target_start_ts": changes["start_ts"],
                    "target_found": target is not None,
                },
            )
            if not target or target["is_closed"]:
                raise RuntimeError("Requested time unavailable")
            if target["players_booked"] + current_players > target["capacity_players"]:
                raise RuntimeError("Requested time lacks capacity")

            await conn.execute(
                """
                UPDATE tee_time_slots
                SET players_booked = GREATEST(players_booked - $1,0), updated_at = now()
                WHERE slot_id = $2
                """,
                current_players,
                current_slot["slot_id"],
            )
            _LOGGER.debug(
                "ReservationStore.modify() decremented players on previous slot.",
                extra={
                    "slot_id": str(current_slot["slot_id"]),
                    "players_removed": current_players,
                },
            )
            await conn.execute(
                """
                UPDATE tee_time_slots
                SET players_booked = players_booked + $1, updated_at = now()
                WHERE slot_id = $2
                """,
                current_players,
                target["slot_id"],
            )
            _LOGGER.debug(
                "ReservationStore.modify() incremented players on target slot.",
                extra={
                    "slot_id": str(target["slot_id"]),
                    "players_added": current_players,
                },
            )
            await conn.execute(
                """
                UPDATE reservations
                SET slot_id = $1,
                    version = version + 1,
                    updated_at = now(),
                    updated_by_call_id = COALESCE($3, updated_by_call_id)
                WHERE confirmation_code = $2
                """,
                target["slot_id"],
                confirmation_code,
                call_id,
            )
            _LOGGER.debug(
                "ReservationStore.modify() updated reservation slot_id.",
                extra={
                    "confirmation_code": confirmation_code,
                    "new_slot_id": str(target["slot_id"]),
                    "call_id": call_id,
                },
            )
            active_slot_id = target["slot_id"]

        # Player-count change flow: apply delta against the active slot.
        if changes.get("players") is not None and changes.get("players") != current_players:
            delta = int(changes["players"]) - int(current_players)
            slot_row = await conn.fetchrow(
                "SELECT * FROM tee_time_slots WHERE slot_id = $1 FOR UPDATE",
                active_slot_id,
            )
            _LOGGER.debug(
                "ReservationStore.modify() locked active slot for player delta.",
                extra={"slot_id": str(active_slot_id), "found": slot_row is not None, "delta": delta},
            )
            if not slot_row:
                raise RuntimeError("Slot not found")
            if delta > 0:
                if (
                    slot_row["players_booked"] + delta > slot_row["capacity_players"]
                    or slot_row["is_closed"]
                ):
                    raise RuntimeError("Not enough capacity for additional players")

            await conn.execute(
                """
                UPDATE tee_time_slots
                SET players_booked = players_booked + $1, updated_at = now()
                WHERE slot_id = $2
                """,
                delta,
                active_slot_id,
            )
            _LOGGER.debug(
                "ReservationStore.modify() updated tee_time_slots players_booked.",
                extra={"slot_id": str(active_slot_id), "player_delta": delta},
            )
            await conn.execute(
                """
                UPDATE reservations
                SET num_players = $1,
                    version = version + 1,
                    updated_at = now(),
                    updated_by_call_id = COALESCE($3, updated_by_call_id)
                WHERE confirmation_code = $2
                """,
                changes["players"],
                confirmation_code,
                call_id,
            )
            _LOGGER.debug(
                "ReservationStore.modify() updated reservation num_players.",
                extra={
                    "confirmation_code": confirmation_code,
                    "new_players": changes["players"],
                    "call_id": call_id,
                },
            )
            current_players = changes["players"]

        # Round-type changes only mutate reservation metadata.
        if changes.get("reservation_type"):
            normalized = "WALKING" if changes["reservation_type"] == "WALKING" else "RIDING"
            await conn.execute(
                """
                UPDATE reservations
                SET reservation_type = $1,
                    version = version + 1,
                    updated_at = now(),
                    updated_by_call_id = COALESCE($3, updated_by_call_id)
                WHERE confirmation_code = $2
                """,
                normalized,
                confirmation_code,
                call_id,
            )
            _LOGGER.debug(
                "ReservationStore.modify() updated reservation_type.",
                extra={
                    "confirmation_code": confirmation_code,
                    "reservation_type": normalized,
                    "call_id": call_id,
                },
            )

        # Persist one high-level change record for downstream audit/tracing.
        change_type = (
            "UPDATE_TIME"
            if changes.get("start_ts") is not None
            else "UPDATE_PLAYERS"
            if changes.get("players") is not None
            else "UPDATE_ROUND_TYPE"
        )
        await conn.execute(
            """
            INSERT INTO reservation_changes
            (reservation_id, change_type, call_id, idempotency_key, after_json)
            SELECT reservation_id, $1, $2, $3, $4
            FROM reservations
            WHERE confirmation_code = $5
            """,
            change_type,
            call_id,
            idempotency_key,
            json.dumps({"confirmation_code": confirmation_code}),
            confirmation_code,
        )
        _LOGGER.debug(
            "ReservationStore.modify() inserted reservation_changes row.",
            extra={
                "confirmation_code": confirmation_code,
                "change_type": change_type,
                "idempotency_key": idempotency_key,
                "call_id": call_id,
            },
        )

        updated = await self.find_by_confirmation(conn, confirmation_code)
        _LOGGER.debug(
            "ReservationStore.modify() returning updated reservation.",
            extra={
                "confirmation_code": confirmation_code,
                "reservation_id": updated.reservation_id if updated else None,
                "slot_id": updated.slot_id if updated else None,
                "players": updated.players if updated else None,
                "status": updated.status if updated else None,
            },
        )
        return updated

    async def cancel(
        self,
        conn: asyncpg.Connection,
        confirmation_code: str,
        idempotency_key: str | None = None,
        call_id: str | None = None,
    ) -> Reservation | None:
        """Cancels a reservation by confirmation code.

        Args:
            conn: Active database connection.
            confirmation_code: Reservation to cancel.
            idempotency_key: Optional key used to deduplicate retried cancels.
            call_id: Optional call identifier associated with this mutation.

        Returns:
            Updated reservation model, or ``None`` if not found.

        Raises:
            RuntimeError: If called outside an active database transaction.
        """
        _LOGGER.debug(
            "ReservationStore.cancel() called.",
            extra={
                "confirmation_code": confirmation_code,
                "idempotency_key": idempotency_key,
                "call_id": call_id,
            },
        )
        self._require_active_transaction(conn, "cancel reservation")

        existing = await self.find_by_confirmation(conn, confirmation_code)
        if not existing:
            _LOGGER.debug(
                "ReservationStore.cancel() target reservation not found.",
                extra={"confirmation_code": confirmation_code},
            )
            return None

        if existing.status == "CANCELLED":
            _LOGGER.debug(
                "ReservationStore.cancel() reservation already cancelled.",
                extra={"confirmation_code": confirmation_code},
            )
            return existing

        reservation_id = await conn.fetchval(
            """
            UPDATE reservations
            SET status = 'CANCELLED',
                updated_at = now(),
                version = version + 1,
                updated_by_call_id = COALESCE($2, updated_by_call_id)
            WHERE confirmation_code = $1
            RETURNING reservation_id
            """,
            confirmation_code,
            call_id,
        )
        _LOGGER.debug(
            "ReservationStore.cancel() updated reservation status to CANCELLED.",
            extra={
                "confirmation_code": confirmation_code,
                "reservation_id": str(reservation_id) if reservation_id else None,
                "call_id": call_id,
            },
        )

        if not reservation_id:
            reservation = await self.find_by_confirmation(conn, confirmation_code)
            _LOGGER.debug(
                "ReservationStore.cancel() no row returned from update; fetched current state.",
                extra={
                    "confirmation_code": confirmation_code,
                    "reservation_id": reservation.reservation_id if reservation else None,
                },
            )
            return reservation

        await conn.execute(
            """
            INSERT INTO reservation_changes
            (reservation_id, change_type, call_id, idempotency_key, before_json, after_json)
            VALUES ($1, 'CANCEL', $2, $3, $4, $5)
            """,
            reservation_id,
            call_id,
            idempotency_key,
            json.dumps({"status": "BOOKED"}),
            json.dumps({"status": "CANCELLED", "confirmation_code": confirmation_code}),
        )
        _LOGGER.debug(
            "ReservationStore.cancel() inserted reservation_changes CANCEL row.",
            extra={
                "reservation_id": str(reservation_id),
                "idempotency_key": idempotency_key,
                "call_id": call_id,
            },
        )

        cancelled = await self.find_by_confirmation(conn, confirmation_code)
        _LOGGER.debug(
            "ReservationStore.cancel() returning cancelled reservation.",
            extra={
                "confirmation_code": confirmation_code,
                "reservation_id": cancelled.reservation_id if cancelled else None,
                "status": cancelled.status if cancelled else None,
            },
        )
        return cancelled

    def _row_to_reservation(self, row: dict[str, Any]) -> Reservation:
        """Maps a joined database row to the public Reservation schema.

        Args:
            row: Joined reservation/slot row from SQL queries.

        Returns:
            Normalized ``Reservation`` model for API responses.
        """
        _LOGGER.debug(
            "ReservationStore._row_to_reservation() called.",
            extra={
                "reservation_id": str(row.get("reservation_id")) if row.get("reservation_id") else None,
                "confirmation_code": row.get("confirmation_code"),
                "slot_id": str(row.get("slot_id")) if row.get("slot_id") else None,
                "status": row.get("status"),
            },
        )
        contact_name = row.get("primary_contact_name") or ""
        contact_phone = row.get("primary_contact_phone_e164") or ""

        reservation = Reservation(
            reservation_id=str(row["reservation_id"]),
            confirmation_code=row.get("confirmation_code") or make_confirmation_code("RES"),
            status="CONFIRMED" if row["status"] == "BOOKED" else "CANCELLED",
            course_id=row["course_id"],
            slot_id=str(row["slot_id"]),
            date=row["date"],
            start_local=row["start_local"],
            players=row["num_players"],
            num_holes=row["num_holes"],
            reservation_type=row["reservation_type"],
            primary_contact={"name": contact_name, "phone_e164": contact_phone},
            created_at=row["created_at"].isoformat(),
            updated_at=row["updated_at"].isoformat() if row.get("updated_at") else None,
            cancelled_at=row["updated_at"].isoformat()
            if row.get("status") == "CANCELLED" and row.get("updated_at")
            else None,
        )
        _LOGGER.debug(
            "ReservationStore._row_to_reservation() produced Reservation model.",
            extra={
                "reservation_id": reservation.reservation_id,
                "confirmation_code": reservation.confirmation_code,
                "status": reservation.status,
                "slot_id": reservation.slot_id,
                "players": reservation.players,
            },
        )
        return reservation
