import { Reservation } from "@golf/shared-schemas";
import { pool } from "../../db/pool.js";
import { withTransaction } from "../../db/tx.js";
import { makeConfirmationCode } from "./confirmationCode.js";

export type CreateReservationInput = {
  idempotency_key: string;
  course_id: string;
  slot_id: string;
  start_ts: string;
  round_type: "NINE" | "EIGHTEEN";
  players: number;
  customer_id: string;
};

export class ReservationStore {
  async findByConfirmation(confirmation_code: string): Promise<Reservation | null> {
    const { rows } = await pool.query(
      `SELECT *, to_char(start_ts, 'HH24:MI') AS start_local, to_char(start_ts, 'YYYY-MM-DD') AS date
       FROM reservations WHERE confirmation_code = $1`,
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
      players: row.party_size,
      primary_contact: { name: "", phone_e164: "" },
      created_at: row.created_at.toISOString(),
      updated_at: row.updated_at?.toISOString(),
      cancelled_at: row.status === "CANCELED" ? row.updated_at?.toISOString() : undefined,
    } as Reservation;
  }

  async create(input: CreateReservationInput): Promise<Reservation> {
    return withTransaction(async (client) => {
      // Idempotency: check existing change by idempotency key
      const existingChange = await client.query(
        `SELECT rc.change_id, r.*, to_char(r.start_ts, 'HH24:MI') AS start_local, to_char(r.start_ts, 'YYYY-MM-DD') AS date
         FROM reservation_changes rc
         JOIN reservations r ON rc.reservation_id = r.reservation_id
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
         (confirmation_code, course_id, slot_id, customer_id, start_ts, round_type, party_size, status)
         VALUES ($1,$2,$3,$4,$5,$6,$7,'BOOKED')
         RETURNING reservation_id, created_at, updated_at`,
        [
          confirmation_code,
          input.course_id,
          input.slot_id,
          input.customer_id,
          input.start_ts,
          input.round_type,
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
        `SELECT *, to_char(start_ts, 'HH24:MI') AS start_local, to_char(start_ts, 'YYYY-MM-DD') AS date
         FROM reservations WHERE reservation_id = $1`,
        [reservation_id]
      );
      return this.rowToReservation(rows[0]);
    });
  }

  async modify(
    confirmation_code: string,
    changes: Partial<{ start_ts: string; players: number }>
  ): Promise<Reservation | null> {
    return withTransaction(async (client) => {
      const existing = await this.findByConfirmation(confirmation_code);
      if (!existing) return null;

      const fields: string[] = [];
      const values: any[] = [];
      let idx = 1;
      if (changes.start_ts) {
        fields.push(`start_ts = $${idx++}`);
        values.push(changes.start_ts);
      }
      if (changes.players) {
        fields.push(`party_size = $${idx++}`);
        values.push(changes.players);
      }
      values.push(confirmation_code);

      if (fields.length === 0) return existing;

      await client.query(
        `UPDATE reservations SET ${fields.join(", ")}, version = version + 1, updated_at = now()
         WHERE confirmation_code = $${idx}`,
        values
      );

      const updated = await this.findByConfirmation(confirmation_code);
      return updated;
    });
  }

  async cancel(confirmation_code: string): Promise<Reservation | null> {
    return withTransaction(async (client) => {
      const existing = await this.findByConfirmation(confirmation_code);
      if (!existing) return null;

      await client.query(
        `UPDATE reservations
         SET status = 'CANCELED', updated_at = now(), version = version + 1
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
      date: row.date,
      start_local: row.start_local,
      players: row.party_size,
      primary_contact: { name: "", phone_e164: "" },
      created_at: row.created_at.toISOString(),
      updated_at: row.updated_at?.toISOString(),
      cancelled_at: row.status === "CANCELED" ? row.updated_at?.toISOString() : undefined,
    };
  }
}
