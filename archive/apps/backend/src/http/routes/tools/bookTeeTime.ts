import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import { BookTeeTimeRequestSchema, BookTeeTimeResponseSchema } from '@golf/shared-schemas';
import { InventoryStore } from '../../../services/inventory/inventoryStore.js';
import { ReservationStore } from '../../../services/reservations/reservationStore.js';
import { env } from '../../../config/env.js';
import { withTransaction } from '../../../db/tx.js';
import { makeConfirmationCode } from '../../../services/reservations/confirmationCode.js';
import { pool } from '../../../db/pool.js';

type Deps = { inventory: InventoryStore; reservations: ReservationStore };

export function registerBookTeeTime(app: FastifyInstance, { inventory, reservations }: Deps) {
  app.post(
    '/v1/tools/book-tee-time',
    async (req: FastifyRequest<{ Body: unknown }>, reply: FastifyReply) => {
      const auth = req.headers['authorization'];
      if (auth !== `Bearer ${env.BACKEND_API_KEY}`) {
        reply.code(401).send({ error: 'Unauthorized' });
        return;
      }
      if (env.DB_READ_ONLY) {
        reply.code(403).send({ error: 'DB is in read-only mode' });
        return;
      }

      const parsed = BookTeeTimeRequestSchema.safeParse(req.body);
      if (!parsed.success) {
        reply.code(400).send({ error: 'Invalid request', details: parsed.error.flatten() });
        return;
      }

      try {
        const resv = await withTransaction(async (client) => {
          // Lock slot
          const slot = await inventory.getSlotForUpdate(client, parsed.data.slot_id);
          if (!slot) {
            throw Object.assign(new Error('slot_id not found'), { statusCode: 404 });
          }
          // Check capacity
          if (slot.players_booked + parsed.data.players > slot.capacity_players || slot.is_closed) {
            throw Object.assign(new Error('Slot no longer available'), { statusCode: 409 });
          }
          // Increment players_booked
          const updatedSlot = await inventory.incrementPlayersBooked(
            client,
            parsed.data.slot_id,
            parsed.data.players
          );
          if (!updatedSlot) {
            throw Object.assign(new Error('Slot no longer available'), { statusCode: 409 });
          }
          const start_ts: string = updatedSlot.start_ts.toISOString();
          // Upsert customer (very simple)
          const customer = await client.query(
            `INSERT INTO customers (phone_e164, full_name)
             VALUES ($1,$2)
             ON CONFLICT (phone_e164) DO UPDATE SET full_name = EXCLUDED.full_name
             RETURNING customer_id`,
            [parsed.data.primary_contact.phone_e164, parsed.data.primary_contact.name]
          );
          const customer_id = customer.rows[0].customer_id;

          const confirmation_code = makeConfirmationCode('RES');
          const resInsert = await client.query(
            `INSERT INTO reservations
             (course_id, slot_id, customer_id, start_ts, num_holes, reservation_type, num_players, status, created_by_call_id)
             VALUES ($1,$2,$3,$4,$5,$6,$7,'BOOKED', NULL)
             RETURNING reservation_id, created_at, updated_at`,
            [
              slot.course_id,
              parsed.data.slot_id,
              customer_id,
              start_ts,
              parsed.data.num_holes,
              parsed.data.reservation_type,
              parsed.data.players,
            ]
          );
          const reservation_id = resInsert.rows[0].reservation_id;

          await client.query(
            `INSERT INTO reservation_changes
             (reservation_id, change_type, idempotency_key, after_json)
             VALUES ($1,'CREATE',$2,$3)`,
            [reservation_id, parsed.data.idempotency_key, JSON.stringify({ confirmation_code })]
          );

          return {
            reservation_id,
            confirmation_code,
            status: 'CONFIRMED',
            course_id: slot.course_id,
            date: start_ts.slice(0, 10),
            start_local: start_ts.slice(11, 16),
            num_holes: parsed.data.num_holes,
            reservation_type: parsed.data.reservation_type,
            players: parsed.data.players,
            primary_contact: parsed.data.primary_contact,
            created_at: resInsert.rows[0].created_at.toISOString(),
            updated_at: resInsert.rows[0].updated_at?.toISOString(),
          };
        });

        reply.send(
          BookTeeTimeResponseSchema.parse({
            confirmation_code: resv.confirmation_code,
            reservation: resv,
          })
        );
      } catch (err: any) {
        const status = err.statusCode ?? 500;
        reply.code(status).send({ error: err.message ?? 'Internal Server Error' });
      }
    }
  );
}
