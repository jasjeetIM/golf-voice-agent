import Fastify, { FastifyInstance } from "fastify";
import { env } from "../config/env.js";
import { registerToolRoutes } from "./routes/tools/index.js";
import { InventoryStore } from "../services/inventory/inventoryStore.js";
import { ReservationStore } from "../services/reservations/reservationStore.js";

export async function createHttpServer(): Promise<FastifyInstance> {
  const app = Fastify({ logger: true });

  const inventory = new InventoryStore();
  const reservations = new ReservationStore();

  app.get("/health", async () => ({ status: "ok", service: "backend" }));

  registerToolRoutes(app, { inventory, reservations });

  await app.listen({ host: "0.0.0.0", port: env.PORT });
  app.log.info(`backend listening on :${env.PORT}`);
  return app;
}
