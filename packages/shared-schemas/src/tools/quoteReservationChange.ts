import { z } from 'zod';

export const QuoteReservationChangeRequestSchema = z.object({
  confirmation_code: z.string().min(1),
  new_slot_id: z.string().optional(),
  new_players: z.number().int().min(1).max(4).optional(),
  new_reservation_type: z.enum(['WALKING', 'RIDING', 'walking', 'riding']).optional(),
});

export const QuoteReservationChangeResponseSchema = z.object({
  can_change: z.boolean(),
  reason: z.string().optional(),
  capacity_ok: z.boolean().optional(),
  target_start_ts: z.string().optional(),
});

export type QuoteReservationChangeRequest = z.infer<typeof QuoteReservationChangeRequestSchema>;
export type QuoteReservationChangeResponse = z.infer<typeof QuoteReservationChangeResponseSchema>;
