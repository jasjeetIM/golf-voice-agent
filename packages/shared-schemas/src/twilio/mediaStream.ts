// packages/shared-schemas/src/twilio/mediaStream.ts
import { z } from "zod";

/**
 * Twilio Media Streams message schema.
 * This is intentionally minimal for the prototype:
 * - start: includes callSid/streamSid
 * - media: includes base64 payload
 * - mark: timing markers
 * - stop: end
 */

export const TwilioStartEventSchema = z.object({
  event: z.literal("start"),
  start: z.object({
    callSid: z.string(),
    streamSid: z.string(),
    // Optional fields exist in Twilio payloads; we ignore for now.
  }),
});

export const TwilioMediaEventSchema = z.object({
  event: z.literal("media"),
  media: z.object({
    payload: z.string(), // base64 audio
    track: z.enum(["inbound", "outbound"]).optional(),
  }),
});

export const TwilioMarkEventSchema = z.object({
  event: z.literal("mark"),
  mark: z.object({
    name: z.string(),
  }),
});

export const TwilioStopEventSchema = z.object({
  event: z.literal("stop"),
  stop: z.object({}).passthrough().optional(),
});

export const TwilioMediaStreamEventSchema = z.union([
  TwilioStartEventSchema,
  TwilioMediaEventSchema,
  TwilioMarkEventSchema,
  TwilioStopEventSchema,
]);

export type TwilioMediaStreamEvent = z.infer<typeof TwilioMediaStreamEventSchema>;
export type TwilioStartEvent = z.infer<typeof TwilioStartEventSchema>;
export type TwilioMediaEvent = z.infer<typeof TwilioMediaEventSchema>;
export type TwilioMarkEvent = z.infer<typeof TwilioMarkEventSchema>;
export type TwilioStopEvent = z.infer<typeof TwilioStopEventSchema>;
