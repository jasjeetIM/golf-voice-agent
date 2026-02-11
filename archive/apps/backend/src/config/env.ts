import { z } from 'zod';

const EnvSchema = z.object({
  PUBLIC_HOST: z.string().default('localhost'),
  PUBLIC_PROTOCOL: z.enum(['http', 'https']).default('http'),
  BACKEND_PORT: z.coerce.number().default(8081),
  BACKEND_URL: z.string().optional(),
  DB_CONNECTION_STRING: z.string().optional(),
  DB_SSL: z.coerce.boolean().default(false),
  DB_POOL_MAX: z.coerce.number().optional(),
  DB_READ_ONLY: z.coerce.boolean().default(false),
  BACKEND_API_KEY: z.string().default('be_api_key'),
  SLOT_INTERVAL_MINUTES: z.coerce.number().default(12),
  TEE_TIME_START_HOUR: z.coerce.number().min(5).max(21).default(7),
  TEE_TIME_END_HOUR: z.coerce.number().min(5).max(21).default(15),
  FORWARD_OPEN_TEE_TIME_DAYS: z.coerce.number().min(1).max(30).default(14),
});

export type Env = z.infer<typeof EnvSchema> & {
  backend_url: string;
  db_connection_string: string;
  port: number;
};

export const env: Env = (() => {
  const parsed = EnvSchema.parse(process.env);
  const port = parsed.BACKEND_PORT;
  const backend_url =
    parsed.BACKEND_URL || `${parsed.PUBLIC_PROTOCOL}://${parsed.PUBLIC_HOST}:${port}`;
  const db_connection_string = parsed.DB_CONNECTION_STRING || 'postgres://localhost:5432/postgres';
  return { ...parsed, backend_url, db_connection_string, port };
})();
