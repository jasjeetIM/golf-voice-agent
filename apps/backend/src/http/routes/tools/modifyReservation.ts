import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import {
  ModifyReservationRequestSchema,
  ModifyReservationResponseSchema,
} from "@golf/shared-schemas";
import { ReservationStore } from "../../../services/reservations/reservationStore.js";
import { env } from "../../../config/env.js";

type Deps = { reservations: ReservationStore };

export function registerModifyReservation(app: FastifyInstance, { reservations }: Deps) {
  app.post(
    "/v1/tools/modify-reservation",
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

      const parsed = ModifyReservationRequestSchema.safeParse(req.body);
      if (!parsed.success) {
        reply.code(400).send({ error: "Invalid request", details: parsed.error.flatten() });
        return;
      }

      const existing = await reservations.findByConfirmation(parsed.data.confirmation_code);
      if (!existing) {
        reply.code(404).send({ error: "Reservation not found" });
        return;
      }

      const updated = await reservations.modify(parsed.data.confirmation_code, parsed.data.changes);
      if (!updated) {
        reply.code(404).send({ error: "Reservation not found" });
        return;
      }

      reply.send(
        ModifyReservationResponseSchema.parse({
          confirmation_code: updated.confirmation_code,
          reservation: updated,
        })
      );
    }
  );
}
