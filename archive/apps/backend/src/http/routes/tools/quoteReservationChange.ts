import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import {
  QuoteReservationChangeRequestSchema,
  QuoteReservationChangeResponseSchema,
} from '@golf/shared-schemas';
import { InventoryStore } from '../../../services/inventory/inventoryStore.js';
import { ReservationStore } from '../../../services/reservations/reservationStore.js';
import { env } from '../../../config/env.js';
import { pool } from '../../../db/pool.js';

type Deps = { inventory: InventoryStore; reservations: ReservationStore };

export function registerQuoteReservationChange(app: FastifyInstance, { reservations }: Deps) {
  app.post(
    '/v1/tools/quote-reservation-change',
    async (req: FastifyRequest<{ Body: unknown }>, reply: FastifyReply) => {
      const auth = req.headers['authorization'];
      if (auth !== `Bearer ${env.BACKEND_API_KEY}`) {
        reply.code(401).send({ error: 'Unauthorized' });
        return;
      }

      const parsed = QuoteReservationChangeRequestSchema.safeParse(req.body);
      if (!parsed.success) {
        reply.code(400).send({ error: 'Invalid request', details: parsed.error.flatten() });
        return;
      }

      const current = await reservations.findByConfirmation(parsed.data.confirmation_code);
      if (!current) {
        reply.code(404).send({ error: 'Reservation not found' });
        return;
      }

      let capacity_ok = true;
      let reason: string | undefined;
      let target_start_ts: string | undefined;

      if (parsed.data.new_slot_id) {
        const { rows } = await pool.query(`SELECT * FROM tee_time_slots WHERE slot_id = $1`, [
          parsed.data.new_slot_id,
        ]);
        const slot = rows[0];
        if (!slot || slot.is_closed) {
          capacity_ok = false;
          reason = 'Requested slot unavailable';
        } else {
          const desiredPlayers = parsed.data.new_players ?? current.players;
          if (slot.players_booked + desiredPlayers > slot.capacity_players) {
            capacity_ok = false;
            reason = 'Not enough capacity';
          } else {
            target_start_ts = slot.start_ts?.toISOString?.() ?? slot.start_ts;
          }
        }
      }

      const can_change = capacity_ok;
      reply.send(
        QuoteReservationChangeResponseSchema.parse({
          can_change,
          reason,
          capacity_ok,
          target_start_ts,
        })
      );
    }
  );
}
