import { Reservation } from "@golf/shared-schemas";
import { pool } from "../../db/pool.js";
import { withTransaction } from "../../db/tx.js";
import { makeConfirmationCode } from "./confirmationCode.js";

export type CreateReservationInput = {
  idempotency_key: string;
  slot_id: string;
  num_holes: 9 | 18;
  reservation_type: "WALKING" | "RIDING";
  players: number;
  customer_id: string;
};

export class ReservationStore {
  async findByConfirmation(confirmation_code: string): Promise<Reservation | null> {
    const { rows } = await pool.query(
      `SELECT r.*, t.course_id, t.start_ts,
              to_char(t.start_ts, 'HH24:MI') AS start_local,
              to_char(t.start_ts, 'YYYY-MM-DD') AS date
       FROM reservations r
       JOIN tee_time_slots t ON r.slot_id = t.slot_id
       WHERE r.confirmation_code = $1`,
      [confirmation_code]
    );
    const row = rows[0];
    if (!row) return null;
    return {
      reservation_id: row.reservation_id,
      confirmation_code: row.confirmation_code,
      status: row.status === "BOOKED" ? "CONFIRMED" : "CANCELLED",
      course_id: row.course_id,
      date: row.date,
      start_local: row.start_local,
      num_holes: row.num_holes,
      reservation_type: row.reservation_type,
      players: row.num_players,
      primary_contact: { name: "", phone_e164: "" },
      created_at: row.created_at.toISOString(),
      updated_at: row.updated_at?.toISOString(),
      cancelled_at: row.status === "CANCELLED" ? row.updated_at?.toISOString() : undefined,
    } as Reservation;
  }

  async create(input: CreateReservationInput): Promise<Reservation> {
    return withTransaction(async (client) => {
      // Idempotency: check existing change by idempotency key
      const existingChange = await client.query(
        `SELECT rc.change_id, r.*, t.course_id, t.start_ts,
                to_char(t.start_ts, 'HH24:MI') AS start_local,
                to_char(t.start_ts, 'YYYY-MM-DD') AS date
         FROM reservation_changes rc
         JOIN reservations r ON rc.reservation_id = r.reservation_id
         JOIN tee_time_slots t ON r.slot_id = t.slot_id
         WHERE rc.idempotency_key = $1`,
        [input.idempotency_key]
      );
      if (existingChange.rows[0]) {
        const r = existingChange.rows[0];
        return this.rowToReservation(r);
      }

      // Insert reservation
      const confirmation_code = makeConfirmationCode("RES");
      const resInsert = await client.query(
        `INSERT INTO reservations
         (confirmation_code, slot_id, customer_id, num_holes, reservation_type, num_players, status)
         VALUES ($1,$2,$3,$4,$5,$6,'BOOKED')
         RETURNING reservation_id, created_at, updated_at`,
        [
          confirmation_code,
          input.slot_id,
          input.customer_id,
          input.num_holes,
          input.reservation_type,
          input.players,
        ]
      );
      const reservation_id = resInsert.rows[0].reservation_id;

      // Change log
      await client.query(
        `INSERT INTO reservation_changes
         (reservation_id, change_type, idempotency_key, after_json)
         VALUES ($1,'CREATE',$2,$3)`,
        [reservation_id, input.idempotency_key, JSON.stringify({ confirmation_code })]
      );

      const { rows } = await client.query(
        `SELECT r.*, t.course_id, t.start_ts,
                to_char(t.start_ts, 'HH24:MI') AS start_local,
                to_char(t.start_ts, 'YYYY-MM-DD') AS date
         FROM reservations r
         JOIN tee_time_slots t ON r.slot_id = t.slot_id
         WHERE r.reservation_id = $1`,
        [reservation_id]
      );
      return this.rowToReservation(rows[0]);
    });
  }

  async modify(
    confirmation_code: string,
    changes: Partial<{ start_ts: string; players: number; reservation_type: "WALKING" | "RIDING"}>
  ): Promise<Reservation | null> {
    return withTransaction(async (client) => {
      const existing = await this.findByConfirmation(confirmation_code);
      if (!existing) return null;

      // Lock current slot
      const currentSlot = await client
        .query(`SELECT * FROM tee_time_slots WHERE slot_id = $1 FOR UPDATE`, [existing.slot_id])
        .then((r) => r.rows[0]);
      if (!currentSlot) throw new Error("Current slot not found");

      // Track which slot is active after potential move
      let activeSlotId = currentSlot.slot_id;
      let currentPlayers = existing.players;

      // update_time: move to a different slot (same course, different start_ts)
      if (changes.start_ts) {
        const target = await client.query(
          `SELECT * FROM tee_time_slots WHERE course_id = $1 AND start_ts = $2 FOR UPDATE`,
          [currentSlot.course_id, changes.start_ts]
        );
        const targetSlot = target.rows[0];
        if (!targetSlot || targetSlot.is_closed) throw new Error("Requested time unavailable");
        if (targetSlot.players_booked + currentPlayers > targetSlot.capacity_players) {
          throw new Error("Requested time lacks capacity");
        }
        // free current slot
        await client.query(
          `UPDATE tee_time_slots SET players_booked = GREATEST(players_booked - $1,0), updated_at = now()
           WHERE slot_id = $2`,
          [currentPlayers, currentSlot.slot_id]
        );
        // book target slot
        await client.query(
          `UPDATE tee_time_slots SET players_booked = players_booked + $1, updated_at = now()
           WHERE slot_id = $2`,
          [currentPlayers, targetSlot.slot_id]
        );
        // move reservation
        await client.query(
          `UPDATE reservations SET slot_id = $1, version = version + 1, updated_at = now()
           WHERE confirmation_code = $2`,
          [targetSlot.slot_id, confirmation_code]
        );
        activeSlotId = targetSlot.slot_id;
      }

      // update_players: adjust num_players and slot occupancy
      if (changes.players !== undefined && changes.players !== currentPlayers) {
        const delta = changes.players - currentPlayers;
        const slotRow = await client
          .query(`SELECT * FROM tee_time_slots WHERE slot_id = $1 FOR UPDATE`, [activeSlotId])
          .then((r) => r.rows[0]);
        if (!slotRow) throw new Error("Slot not found");
        if (delta > 0) {
          if (slotRow.players_booked + delta > slotRow.capacity_players || slotRow.is_closed) {
            throw new Error("Not enough capacity for additional players");
          }
        }
        await client.query(
          `UPDATE tee_time_slots
           SET players_booked = players_booked + $1, updated_at = now()
           WHERE slot_id = $2`,
          [delta, activeSlotId]
        );
        await client.query(
          `UPDATE reservations
           SET num_players = $1, version = version + 1, updated_at = now()
           WHERE confirmation_code = $2`,
          [changes.players, confirmation_code]
        );
        currentPlayers = changes.players;
      }

      // update_type: change walking/riding
      if (changes.reservation_type) {
        const normalizedType =
           changes.reservation_type === "WALKING"
            ? "WALKING"
            : "RIDING";
        await client.query(
          `UPDATE reservations
           SET reservation_type = $1, version = version + 1, updated_at = now()
           WHERE confirmation_code = $2`,
          [normalizedType, confirmation_code]
        );
      }

      // Log change
      const changeType =
        changes.start_ts !== undefined
          ? "UPDATE_TIME"
          : changes.players !== undefined
            ? "UPDATE_PLAYERS"
            : "UPDATE_ROUND_TYPE";
      await client.query(
        `INSERT INTO reservation_changes (reservation_id, change_type, after_json)
         SELECT reservation_id, $1, $2 FROM reservations WHERE confirmation_code = $3`,
        [changeType, JSON.stringify({ confirmation_code }), confirmation_code]
      );

      return this.findByConfirmation(confirmation_code);
    });
  }

  async cancel(confirmation_code: string): Promise<Reservation | null> {
    return withTransaction(async (client) => {
      const existing = await this.findByConfirmation(confirmation_code);
      if (!existing) return null;

      await client.query(
        `UPDATE reservations
         SET status = 'CANCELLED', updated_at = now(), version = version + 1
         WHERE confirmation_code = $1`,
        [confirmation_code]
      );

      const updated = await this.findByConfirmation(confirmation_code);
      return updated;
    });
  }

  private rowToReservation(row: any): Reservation {
    return {
      reservation_id: row.reservation_id,
      confirmation_code: row.confirmation_code ?? makeConfirmationCode("RES"),
      status: row.status === "BOOKED" ? "CONFIRMED" : "CANCELLED",
      course_id: row.course_id,
      slot_id: row.slot_id,
      date: row.date,
      start_local: row.start_local,
      players: row.num_players,
      num_holes: row.num_holes,
      reservation_type: row.reservation_type,
      primary_contact: { name: "", phone_e164: "" },
      created_at: row.created_at.toISOString(),
      updated_at: row.updated_at?.toISOString(),
      cancelled_at: row.status === "CANCELLED" ? row.updated_at?.toISOString() : undefined,
    };
  }
}
