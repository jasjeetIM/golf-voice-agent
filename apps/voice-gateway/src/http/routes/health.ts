import type { FastifyReply, FastifyRequest } from "fastify";

export async function healthHandler(
  _req: FastifyRequest,
  reply: FastifyReply
) {
  reply.send({ status: "ok" });
}
