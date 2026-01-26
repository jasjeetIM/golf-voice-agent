import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import {
  GetReservationDetailsRequestSchema,
  GetReservationDetailsResponseSchema,
} from '@golf/shared-schemas';
import { ReservationStore } from '../../../services/reservations/reservationStore.js';
import { env } from '../../../config/env.js';

type Deps = { reservations: ReservationStore };

export function registerGetReservationDetails(app: FastifyInstance, { reservations }: Deps) {
  app.post(
    '/v1/tools/get-reservation-details',
    async (req: FastifyRequest<{ Body: unknown }>, reply: FastifyReply) => {
      const auth = req.headers['authorization'];
      if (auth !== `Bearer ${env.BACKEND_API_KEY}`) {
        reply.code(401).send({ error: 'Unauthorized' });
        return;
      }

      const parsed = GetReservationDetailsRequestSchema.safeParse(req.body);
      if (!parsed.success) {
        reply.code(400).send({ error: 'Invalid request', details: parsed.error.flatten() });
        return;
      }

      const reservation = await reservations.findByConfirmation(parsed.data.confirmation_code);
      if (!reservation) {
        reply.code(404).send({ error: 'Reservation not found' });
        return;
      }

      reply.send(GetReservationDetailsResponseSchema.parse({ reservation }));
    }
  );
}
