import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import {
  CheckSlotCapacityRequestSchema,
  CheckSlotCapacityResponseSchema,
} from '@golf/shared-schemas';
import { InventoryStore } from '../../../services/inventory/inventoryStore.js';
import { env } from '../../../config/env.js';
import { pool } from '../../../db/pool.js';

type Deps = { inventory: InventoryStore };

export function registerCheckSlotCapacity(app: FastifyInstance, { inventory }: Deps) {
  app.post(
    '/v1/tools/check-slot-capacity',
    async (req: FastifyRequest<{ Body: unknown }>, reply: FastifyReply) => {
      const auth = req.headers['authorization'];
      if (auth !== `Bearer ${env.BACKEND_API_KEY}`) {
        reply.code(401).send({ error: 'Unauthorized' });
        return;
      }

      const parsed = CheckSlotCapacityRequestSchema.safeParse(req.body);
      if (!parsed.success) {
        reply.code(400).send({ error: 'Invalid request', details: parsed.error.flatten() });
        return;
      }

      const { rows } = await pool.query(`SELECT * FROM tee_time_slots WHERE slot_id = $1`, [
        parsed.data.slot_id,
      ]);
      const slotRow = rows[0];
      if (!slotRow) {
        reply.code(404).send({ error: 'slot_id not found' });
        return;
      }

      const available =
        !slotRow.is_closed &&
        slotRow.players_booked + parsed.data.players <= slotRow.capacity_players;

      reply.send(
        CheckSlotCapacityResponseSchema.parse({
          available,
          capacity_players: slotRow.capacity_players,
          players_booked: slotRow.players_booked,
        })
      );
    }
  );
}
