import { z } from 'zod';

export const DateSchema = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/)
  .refine(
    (s) => {
      const d = new Date(`${s}TOO:00:00Z`);
      return !Number.isNaN(d.getTime()) && d.toISOString().startsWith(s);
    },
    { message: 'Invalid calendar date.' }
  );
