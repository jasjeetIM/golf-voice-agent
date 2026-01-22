import type { FastifyReply, FastifyRequest } from "fastify";
import type { Env } from "../../config/env";
import { buildConnectStreamTwiML } from "../../ws/twilio/twiml";

export type TwilioInboundRequest = FastifyRequest<{Body: Record<string, string>;}>;

// POST /twilio/inbound -> returns TwiML that starts the Media Stream
export async function inboundHandler(
  request: TwilioInboundRequest,
  reply: FastifyReply,
  env: Env
) {
  const wsUrl = env.public_voice_url.replace(/^http/, "ws") + "/twilio/stream";
  const twiml = buildConnectStreamTwiML(wsUrl);
  reply.type("text/xml").send(twiml);
}
