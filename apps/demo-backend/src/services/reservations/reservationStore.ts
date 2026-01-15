import { Reservation } from "@golf/shared-schemas";
import { makeConfirmationCode } from "./confirmationCode.js";

export type CreateReservationInput = {
  idempotency_key: string;
  course_id: string;
  date: string;
  start_local: string;
  players: number;
  primary_contact: { name: string; phone_e164: string };
};

export class ReservationStore {
  private byConfirmation: Map<string, Reservation> = new Map();
  private byIdempotency: Map<string, string> = new Map(); // idemKey -> confirmation_code

  create(input: CreateReservationInput): Reservation {
    const existingCode = this.byIdempotency.get(input.idempotency_key);
    if (existingCode) {
      const existing = this.byConfirmation.get(existingCode);
      if (existing) return existing;
    }

    const confirmation_code = makeConfirmationCode("RES");
    const reservation_id = `res_${Math.random().toString(16).slice(2)}`;
    const now = new Date().toISOString();

    const res: Reservation = {
      reservation_id,
      confirmation_code,
      status: "CONFIRMED",
      course_id: input.course_id,
      date: input.date,
      start_local: input.start_local,
      players: input.players,
      primary_contact: input.primary_contact,
      created_at: now,
    };

    this.byConfirmation.set(confirmation_code, res);
    this.byIdempotency.set(input.idempotency_key, confirmation_code);
    return res;
  }

  get(confirmation_code: string): Reservation | null {
    return this.byConfirmation.get(confirmation_code) ?? null;
  }

  modify(confirmation_code: string, changes: Partial<Pick<Reservation, "start_local" | "players">>): Reservation | null {
    const existing = this.get(confirmation_code);
    if (!existing) return null;
    if (existing.status === "CANCELLED") return existing;

    const updated: Reservation = {
      ...existing,
      ...changes,
      updated_at: new Date().toISOString(),
    };

    this.byConfirmation.set(confirmation_code, updated);
    return updated;
  }

  cancel(confirmation_code: string): Reservation | null {
    const existing = this.get(confirmation_code);
    if (!existing) return null;
    if (existing.status === "CANCELLED") return existing;

    const updated: Reservation = {
      ...existing,
      status: "CANCELLED",
      cancelled_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    this.byConfirmation.set(confirmation_code, updated);
    return updated;
  }
}
