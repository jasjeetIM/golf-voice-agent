import { z } from 'zod';
import { E164PhoneSchema } from '../domain/reservation.js';

export const SendSmsConfirmationRequestSchema = z.object({
  confirmation_code: z.string().min(1),
  phone_e164: E164PhoneSchema,
});

export const SendSmsConfirmationResponseSchema = z.object({
  status: z.enum(['queued', 'sent', 'failed']).default('queued'),
  confirmation_code: z.string(),
  phone_e164: E164PhoneSchema,
});

export type SendSmsConfirmationRequest = z.infer<typeof SendSmsConfirmationRequestSchema>;
export type SendSmsConfirmationResponse = z.infer<typeof SendSmsConfirmationResponseSchema>;
