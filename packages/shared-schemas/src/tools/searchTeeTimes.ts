// packages/shared-schemas/src/tools/searchTeeTimes.ts
import { z } from "zod";
import { MoneySchema } from "../domain/money.js";
import { CourseIdSchema } from "../domain/course.js";
import { DateSchema } from "../domain/date.js";

export const TimeWindowSchema = z.object({
  start_local: z.string().regex(/^\d{2}:\d{2}$/, "Expected HH:MM"),
  end_local: z.string().regex(/^\d{2}:\d{2}$/, "Expected HH:MM"),
}).refine(
  (tw) => tw.start_local < tw.end_local,
  {
    message: "start_local must be before end_local."
  }
);

export const SearchTeeTimesRequestSchema = z.object({
  course_id: CourseIdSchema,
  date: DateSchema,
  time_window: TimeWindowSchema,
  players: z.number().int().min(1).max(4),
  holes: z.union([z.literal(9), z.literal(18)]).default(18),
  WALKING_preference: z.enum(["WALKING", "RIDING", "either"]).default("either"),
  max_results: z.number().int().min(1).max(10).default(5),
});

export const TeeTimeOptionSchema = z.object({
  slot_id: z.string(),
  start_local: z.string().regex(/^\d{2}:\d{2}$/),
  duration_min: z.number().int().positive(),
  players_allowed: z.array(z.number().int().min(1).max(4)).min(1),
  price: MoneySchema,
  constraints: z.object({
    cart_required: z.boolean(),
    cancellation_policy: z.string(),
  }),
});

export const SearchTeeTimesResponseSchema = z.object({
  course_id: CourseIdSchema,
  date: DateSchema,
  timezone: z.string(), // "America/New_York"
  options: z.array(TeeTimeOptionSchema),
  freshness: z.object({
    generated_at: z.string(), // ISO
    ttl_seconds: z.number().int().positive(),
  }),
});

export type SearchTeeTimesRequest = z.infer<typeof SearchTeeTimesRequestSchema>;
export type SearchTeeTimesResponse = z.infer<typeof SearchTeeTimesResponseSchema>;
export type TeeTimeOption = z.infer<typeof TeeTimeOptionSchema>;
