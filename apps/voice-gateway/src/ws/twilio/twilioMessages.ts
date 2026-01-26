import { z } from 'zod';

const startEventSchema = z.object({
  event: z.literal('start'),
  start: z.object({
    accountSid: z.string(),
    streamSid: z.string(),
    callSid: z.string(),
    tracks: z.array(z.string()).optional(),
    mediaFormat: z
      .object({
        encoding: z.string(),
        sampleRate: z.number(),
        channels: z.number(),
      })
      .optional(),
    customParameters: z.record(z.string(), z.string()).optional(),
  }),
  streamSid: z.string().optional(),
});

const mediaEventSchema = z.object({
  event: z.literal('media'),
  streamSid: z.string(),
  media: z.object({
    payload: z.string(),
    track: z.string(),
    chunk: z.number(),
    timestamp: z.string(),
  }),
});

const markEventSchema = z.object({
  event: z.literal('mark'),
  streamSid: z.string(),
  mark: z.object({
    name: z.string(),
    value: z.string().optional(),
  }),
});

const stopEventSchema = z.object({
  event: z.literal('stop'),
  streamSid: z.string().optional(),
  stop: z.object({
    accountSid: z.string().optional(),
    callSid: z.string().optional(),
    streamSid: z.string(),
  }),
});

const twilioMessageSchema = z.discriminatedUnion('event', [
  startEventSchema,
  mediaEventSchema,
  markEventSchema,
  stopEventSchema,
]);

export type TwilioMessage = z.infer<typeof twilioMessageSchema>;

export function parseTwilioMessage(raw: string): TwilioMessage {
  return twilioMessageSchema.parse(JSON.parse(raw));
}
