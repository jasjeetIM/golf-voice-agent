import { z } from "zod";

const EnvSchema = z.object({
  PORT: z.coerce.number().default(6060),
  DATABASE_URL: z.string().min(1, "DATABASE_URL is required"),
  DB_SSL: z.coerce.boolean().default(false),
  DB_POOL_MAX: z.coerce.number().optional(),
  API_KEY: z.string().default("dev_backend_key"),
  READ_ONLY: z.coerce.boolean().default(false),
});

export const env = EnvSchema.parse(process.env);
export type Env = z.infer<typeof EnvSchema>;
