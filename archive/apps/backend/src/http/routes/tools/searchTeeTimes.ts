import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import { SearchTeeTimesRequestSchema, SearchTeeTimesResponseSchema } from '@golf/shared-schemas';
import { InventoryStore } from '../../../services/inventory/inventoryStore.js';
import { env } from '../../../config/env.js';

type Deps = { inventory: InventoryStore };

export function registerSearchTeeTimes(app: FastifyInstance, { inventory }: Deps) {
  app.post(
    '/v1/tools/search-tee-times',
    async (req: FastifyRequest<{ Body: unknown }>, reply: FastifyReply) => {
      const auth = req.headers['authorization'];
      if (auth !== `Bearer ${env.BACKEND_API_KEY}`) {
        reply.code(401).send({ error: 'Unauthorized' });
        return;
      }

      const parsed = SearchTeeTimesRequestSchema.safeParse(req.body);
      if (!parsed.success) {
        reply.code(400).send({ error: 'Invalid request', details: parsed.error.flatten() });
        return;
      }

      const options = await inventory.search(parsed.data);
      const response = {
        course_id: parsed.data.course_id,
        date: parsed.data.date,
        timezone: 'America/New_York',
        options,
        freshness: {
          generated_at: new Date().toISOString(),
          ttl_seconds: 300,
        },
      };

      reply.send(SearchTeeTimesResponseSchema.parse(response));
    }
  );
}
