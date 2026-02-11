import Fastify from 'fastify';
import fastifyFormBody from '@fastify/formbody';
import { inboundHandler, TwilioInboundRequest } from './routes/twilio.inbound';
import { healthHandler } from './routes/health';
import type { Env } from '../config/env';

// Factory for the HTTP server (Twilio webhook + health)
export async function createHttpServer(env: Env) {
  const app = Fastify({ logger: { level: env.LOG_LEVEL } });

  // Twilio webhooks may be urlencoded; enable form parsing
  await app.register(fastifyFormBody);

  app.post('/twilio/inbound', (request: TwilioInboundRequest, reply) =>
    inboundHandler(request, reply, env)
  );

  app.get('/health', healthHandler);

  return app;
}
