import { z } from "zod";

export const CancelReservationRequestSchema = z.object({
  confirmation_code: z.string().min(1),
  idempotency_key: z.string().min(1),
});

export const CancelReservationResponseSchema = z.object({
  confirmation_code: z.string(),
  status: z.enum(["CANCELLED", "CONFIRMED"]),
  cancelled_at: z.string().optional(),
  policy: z
    .object({
      fee_applied: z.boolean(),
      message: z.string(),
    })
    .optional(),
});

export type CancelReservationRequest = z.infer<typeof CancelReservationRequestSchema>;
export type CancelReservationResponse = z.infer<typeof CancelReservationResponseSchema>;
