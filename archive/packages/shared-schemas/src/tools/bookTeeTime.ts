import { z } from 'zod';
import {
  ReservationSchema,
  E164PhoneSchema,
  NumHolesSchema,
  ReservationTypeSchema,
} from '../domain/reservation.js';

export const BookTeeTimeRequestSchema = z.object({
  idempotency_key: z.string().min(1),
  slot_id: z.string().min(1),
  primary_contact: z.object({
    name: z.string().min(1),
    phone_e164: E164PhoneSchema,
  }),
  players: z.number().int().min(1).max(4),
  num_holes: NumHolesSchema,
  reservation_type: ReservationTypeSchema,
});

export const BookTeeTimeResponseSchema = z.object({
  confirmation_code: z.string(),
  reservation: ReservationSchema,
});

export type BookTeeTimeRequest = z.infer<typeof BookTeeTimeRequestSchema>;
export type BookTeeTimeResponse = z.infer<typeof BookTeeTimeResponseSchema>;
