// Domain types placeholder
import { z } from "zod";
import { CourseIdSchema } from "./course.js";

export const E164PhoneSchema = z.string().regex(/^\+\d{8,15}$/, "Expected E.164 phone number like +13361117999");
export const ReservationStatusSchema = z.enum([
    "CONFIRMED", 
    "CANCELLED",
]);

export const ReservationSchema = z.object({
  reservation_id: z.string(),
  confirmation_code: z.string(),
  status: ReservationStatusSchema,
  course_id: CourseIdSchema,
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  start_local: z.string().regex(/^\d{2}:\d{2}$/),
  players: z.number().int().min(1).max(4),
  primary_contact: z.object({ name: z.string().min(1), phone_e164: E164PhoneSchema }),
  created_at: z.string(),
  updated_at: z.string().optional(),
  cancelled_at: z.string().optional(),
});


export type Reservation = z.infer<typeof ReservationSchema>;
export type ReservationStatus = z.infer<typeof ReservationStatusSchema>;
