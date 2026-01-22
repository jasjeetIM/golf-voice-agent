import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import {
  SendSmsConfirmationRequestSchema,
  SendSmsConfirmationResponseSchema,
} from "@golf/shared-schemas";
import { env } from "../../../config/env.js";
import { ReservationStore } from "apps/backend/src/services/reservations/reservationStore.js";

type Deps = { reservations: ReservationStore };

export function registerSendSmsConfirmation(app: FastifyInstance, { reservations }: Deps) {
  app.post(
    "/v1/tools/send-sms-confirmation",
    async (
      req: FastifyRequest<{ Body: unknown }>,
      reply: FastifyReply
    ) => {
      const auth = req.headers["authorization"];
      if (auth !== `Bearer ${env.BACKEND_API_KEY}`) {
        reply.code(401).send({ error: "Unauthorized" });
        return;
      }
      const parsed = SendSmsConfirmationRequestSchema.safeParse(req.body);
      if (!parsed.success) {
        reply.code(400).send({ error: "Invalid request", details: parsed.error.flatten() });
        return;
      }

      // Stub: In a real impl, enqueue an SMS in notifications_outbox
      reply.send(
        SendSmsConfirmationResponseSchema.parse({
          status: "queued",
          confirmation_code: parsed.data.confirmation_code,
          phone_e164: parsed.data.phone_e164,
        })
      );
    }
  );
}
