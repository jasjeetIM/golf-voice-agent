// Domain types placeholder
import { z } from "zod";

export const CourseIdSchema = z.string().min(1);
export const TimezoneSchema = z.string().min(1);

export type CourseId = z.infer<typeof CourseIdSchema>;
export type Timezone = z.infer<typeof TimezoneSchema>;
