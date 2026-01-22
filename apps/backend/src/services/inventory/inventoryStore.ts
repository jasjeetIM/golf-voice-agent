import { SearchTeeTimesRequest, TeeTimeOption } from "@golf/shared-schemas";
import { pool, withClient } from "../../db/pool.js";

export class InventoryStore {
  async search(req: SearchTeeTimesRequest): Promise<TeeTimeOption[]> {
    const sql = `
      SELECT slot_id, start_ts, capacity_players, players_booked, base_price_cents, currency, rules_json
      FROM tee_time_slots
      WHERE course_id = $1
        AND start_ts::date = $2::date
        AND start_ts::time >= $3::time
        AND start_ts::time <= $4::time
        AND is_closed = FALSE
        AND players_booked + $5 <= capacity_players
      ORDER BY start_ts
      LIMIT $6
    `;
    const params = [
      req.course_id,
      req.date,
      req.time_window.start_local,
      req.time_window.end_local,
      req.players,
      req.max_results,
    ];
    const { rows } = await pool.query(sql, params);

    return rows.map((row) => {
      const start_local = row.start_ts.toISOString().slice(11, 16); // HH:MM
      const base = row.base_price_cents ?? 0;
      return {
        slot_id: row.slot_id,
        start_local,
        duration_min: 240,
        players_allowed: [1, 2, 3, 4].filter((p) => p + row.players_booked <= row.capacity_players),
        price: {
          currency: row.currency || "USD",
          amount_per_player: base / 100,
          amount_total: (base / 100) * req.players,
        },
        constraints: {
          cart_required: false,
          cancellation_policy: "Cancel >= 24h to avoid fee",
        },
      } satisfies TeeTimeOption;
    });
  }

  async getSlotForUpdate(client: any, slot_id: string) {
    const { rows } = await client.query(
      `SELECT * FROM tee_time_slots WHERE slot_id = $1 FOR UPDATE`,
      [slot_id]
    );
    return rows[0] || null;
  }

  async incrementPlayersBooked(client: any, slot_id: string, players: number) {
    const result = await client.query(
      `UPDATE tee_time_slots
       SET players_booked = players_booked + $2, updated_at = now()
       WHERE slot_id = $1 AND players_booked + $2 <= capacity_players AND is_closed = FALSE
       RETURNING *`,
      [slot_id, players]
    );
    return result.rowCount === 1 ? result.rows[0] : null;
  }
}
