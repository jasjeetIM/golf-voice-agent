import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import {
  CancelReservationRequestSchema,
  CancelReservationResponseSchema,
} from "@golf/shared-schemas";
import { ReservationStore } from "../../../services/reservations/reservationStore.js";
import { env } from "../../../config/env.js";

type Deps = { reservations: ReservationStore };

export function registerCancelReservation(app: FastifyInstance, { reservations }: Deps) {
  app.post(
    "/v1/tools/cancel-reservation",
    async (
      req: FastifyRequest<{ Body: unknown }>,
      reply: FastifyReply
    ) => {
      const auth = req.headers["authorization"];
      if (auth !== `Bearer ${env.BACKEND_API_KEY}`) {
        reply.code(401).send({ error: "Unauthorized" });
        return;
      }
      if (env.DB_READ_ONLY) {
        reply.code(403).send({ error: "DB is in read-only mode" });
        return;
      }

      const parsed = CancelReservationRequestSchema.safeParse(req.body);
      if (!parsed.success) {
        reply.code(400).send({ error: "Invalid request", details: parsed.error.flatten() });
        return;
      }

      const updated = await reservations.cancel(parsed.data.confirmation_code);
      if (!updated) {
        reply.code(404).send({ error: "Reservation not found" });
        return;
      }

      reply.send(
        CancelReservationResponseSchema.parse({
          confirmation_code: updated.confirmation_code,
          status: updated.status,
          cancelled_at: updated.cancelled_at,
          policy: {
            fee_applied: false,
            message: "Cancelled successfully.",
          },
        })
      );
    }
  );
}
