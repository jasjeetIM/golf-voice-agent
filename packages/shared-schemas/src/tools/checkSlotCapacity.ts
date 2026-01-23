import { z } from "zod";

export const CheckSlotCapacityRequestSchema = z.object({
  slot_id: z.string().min(1),
  players: z.number().int().min(1).max(4),
});

export const CheckSlotCapacityResponseSchema = z.object({
  available: z.boolean(),
  capacity_players: z.number().int(),
  players_booked: z.number().int(),
});

export type CheckSlotCapacityRequest = z.infer<typeof CheckSlotCapacityRequestSchema>;
export type CheckSlotCapacityResponse = z.infer<typeof CheckSlotCapacityResponseSchema>;
