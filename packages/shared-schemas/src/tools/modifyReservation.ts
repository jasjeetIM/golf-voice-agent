import { z } from "zod";
import { ReservationSchema } from "../domain/reservation.js";

export const ModifyReservationRequestSchema = z.object({
  confirmation_code: z.string().min(1),
  idempotency_key: z.string().min(1),
  changes: z.object({
    start_local: z.string().regex(/^\d{2}:\d{2}$/).optional(),
    players: z.number().int().min(1).max(4).optional(),
    reservation_type: z.enum(["WALKING", "RIDING", "walking", "riding"]).optional(),
  }).refine((obj) => obj.start_local !== undefined || obj.players !== undefined || obj.reservation_type !== undefined, {
    message: "At least one change is required",
  }),
});

export const ModifyReservationResponseSchema = z.object({
  confirmation_code: z.string(),
  reservation: ReservationSchema,
});

export type ModifyReservationRequest = z.infer<typeof ModifyReservationRequestSchema>;
export type ModifyReservationResponse = z.infer<typeof ModifyReservationResponseSchema>;
