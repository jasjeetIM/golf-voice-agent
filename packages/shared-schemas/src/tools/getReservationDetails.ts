import { z } from "zod";
import { ReservationSchema } from "../domain/reservation.js";

export const GetReservationDetailsRequestSchema = z.object({
  confirmation_code: z.string().min(1),
});

export const GetReservationDetailsResponseSchema = z.object({
  reservation: ReservationSchema,
});

export type GetReservationDetailsRequest = z.infer<typeof GetReservationDetailsRequestSchema>;
export type GetReservationDetailsResponse = z.infer<typeof GetReservationDetailsResponseSchema>;
