import dotenv from 'dotenv';
import pg from 'pg';
import { env } from '../src/config/env.js';

const connectionString = env.DB_CONNECTION_STRING || 'postgres://localhost:5432/postgres';

async function main() {
  const pool = new pg.Pool({ connectionString });
  try {
    await pool.query('BEGIN');

    // Ensure course exists
    await pool.query(
      `INSERT INTO courses (course_id, course_name, timezone)
       VALUES ($1, $2, $3)
       ON CONFLICT (course_id) DO NOTHING`,
      ['0', 'Demo Course 0', 'America/New_York']
    );

    const startMinutes = env.TEE_TIME_START_HOUR * 60; // start
    const endMinutes = env.TEE_TIME_END_HOUR * 60; // end
    const intervalMinutes = env.SLOT_INTERVAL_MINUTES;

    const today = new Date();
    today.setHours(0, 0, 0, 0);

    let total = 0;
    for (let dayOffset = 1; dayOffset <= env.FORWARD_OPEN_TEE_TIME_DAYS; dayOffset++) {
      const day = new Date(today);
      day.setDate(today.getDate() + dayOffset);

      const slots: { start: Date; priceCents: number }[] = [];
      const toUTC = (hours: number, minutes: number) =>
        new Date(Date.UTC(day.getFullYear(), day.getMonth(), day.getDate(), hours, minutes));

      for (let m = startMinutes; m <= endMinutes; m += intervalMinutes) {
        const hour = Math.floor(m / 60);
        const minute = m % 60;
        const priceCents = m < 15 * 60 ? 10000 : 5000; // before 3pm -> $100, else $50
        slots.push({ start: toUTC(hour, minute), priceCents });
      }

      for (const slot of slots) {
        await pool.query(
          `INSERT INTO tee_time_slots (course_id, start_ts, capacity_players, base_price_cents, currency, is_closed, players_booked)
           VALUES ($1, $2, $3, $4, 'USD', FALSE, 0)
           ON CONFLICT (course_id, start_ts) DO UPDATE
             SET base_price_cents = EXCLUDED.base_price_cents,
                 updated_at = now()`,
          ['0', slot.start.toISOString(), 4, slot.priceCents]
        );
      }
      total += slots.length;
    }

    await pool.query('COMMIT');
    console.log(
      `Inserted/updated ${total} slots for course 0 over the next 14 days (${env.TEE_TIME_START_HOUR}am-${env.TEE_TIME_END_HOUR}pm, ${intervalMinutes}-min cadence).`
    );
  } catch (err) {
    await pool.query('ROLLBACK');
    console.error(err);
    process.exitCode = 1;
  } finally {
    await pool.end();
  }
}

main();
