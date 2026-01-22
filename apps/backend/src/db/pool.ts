import pg from "pg";
import { env } from "../config/env.js";

const { Pool } = pg;

// Shared Postgres connection pool
export const pool = new Pool({
  connectionString: env.db_connection_string,
  ssl: env.DB_SSL ? { rejectUnauthorized: false } : undefined,
  max: env.DB_POOL_MAX || 10,
  idleTimeoutMillis: 30_000,
});

export async function withClient<T>(fn: (client: pg.PoolClient) => Promise<T>): Promise<T> {
  const client = await pool.connect();
  try {
    return await fn(client);
  } finally {
    client.release();
  }
}
