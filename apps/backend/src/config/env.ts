import { z } from "zod";

const EnvSchema = z.object({
  PUBLIC_HOST: z.string().default("localhost"),
  PUBLIC_PROTOCOL: z.enum(["http", "https"]).default("http"),
  BACKEND_PORT: z.coerce.number().default(8081),
  BACKEND_URL: z.string().optional(),
  DB_CONNECTION_STRING: z.string().optional(),
  DB_SSL: z.coerce.boolean().default(false),
  DB_POOL_MAX: z.coerce.number().optional(),
  DB_READ_ONLY: z.coerce.boolean().default(false),
  DB_API_KEY: z.string().default("be_api_key"),
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
    parsed.BACKEND_URL ||
    `${parsed.PUBLIC_PROTOCOL}://${parsed.PUBLIC_HOST}:${port}`;
  const db_connection_string =
    parsed.DB_CONNECTION_STRING || "postgres://localhost:5432/postgres";
  const api_key = parsed.API_KEY || parsed.DB_API_KEY;
  return { ...parsed, backend_url, db_connection_string, port, API_KEY: api_key };
})();
