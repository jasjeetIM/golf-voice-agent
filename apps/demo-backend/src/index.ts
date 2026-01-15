// apps/demo-backend/src/index.ts
import Fastify from "fastify";
import dotenv from "dotenv";
import { z } from "zod";

import {
  SearchTeeTimesRequestSchema,
  SearchTeeTimesResponseSchema,
  ReservationSchema,
} from "@golf/shared-schemas";

import { InventoryStore } from "./services/inventory/inventoryStore.js";
import { ReservationStore } from "./services/reservations/reservationStore.js";

dotenv.config();

const EnvSchema = z.object({
  DEMO_BACKEND_PORT: z.coerce.number().default(8081),
  DEMO_API_KEY: z.string().default("dev_demo_key"),
  DEMO_READ_ONLY: z
    .string()
    .optional()
    .transform((v) => v === "true")
    .default(false),
});

const env = EnvSchema.parse(process.env);

const app = Fastify({ logger: true });
const inventory = new InventoryStore();
const reservations = new ReservationStore();

app.get("/health", async () => ({ status: "ok", service: "demo-backend" }));

function requireAuth(req: any) {
  const auth = req.headers["authorization"];
  const expected = `Bearer ${env.DEMO_API_KEY}`;
  if (auth !== expected) {
    const err = new Error("Unauthorized");
    (err as any).statusCode = 401;
    throw err;
  }
}

app.post("/v1/tools/search-tee-times", async (req, reply) => {
  requireAuth(req);

  const parsed = SearchTeeTimesRequestSchema.safeParse(req.body);
  if (!parsed.success) {
    reply.code(400);
    return { error: "Invalid request", details: parsed.error.flatten() };
  }

  const options = inventory.search(parsed.data);

  const response = {
    course_id: parsed.data.course_id,
    date: parsed.data.date,
    timezone: "America/New_York",
    options,
    freshness: {
      generated_at: new Date().toISOString(),
      ttl_seconds: 300,
    },
  };

  return SearchTeeTimesResponseSchema.parse(response);
});

const BookRequestSchema = z.object({
  idempotency_key: z.string().min(1),
  slot_id: z.string().min(1),
  primary_contact: z.object({
    name: z.string().min(1),
    phone_e164: z.string().min(1), // we enforce stricter later
  }),
  players: z.number().int().min(1).max(4),
});

app.post("/v1/tools/book-tee-time", async (req, reply) => {
  requireAuth(req);
  if (env.DEMO_READ_ONLY) {
    reply.code(403);
    return { error: "Demo is in read-only mode" };
  }

  const parsed = BookRequestSchema.safeParse(req.body);
  if (!parsed.success) {
    reply.code(400);
    return { error: "Invalid request", details: parsed.error.flatten() };
  }

  const slot = inventory.getSlotById(parsed.data.slot_id);
  if (!slot) {
    reply.code(404);
    return { error: "slot_id not found" };
  }

  // Reserve slot (remove from inventory for realism)
  const ok = inventory.reserveSlot(parsed.data.slot_id);
  if (!ok) {
    reply.code(409);
    return { error: "Slot no longer available" };
  }

  const res = reservations.create({
    idempotency_key: parsed.data.idempotency_key,
    course_id: slot.course_id,
    date: slot.date,
    start_local: slot.option.start_local,
    players: parsed.data.players,
    primary_contact: parsed.data.primary_contact,
  });

  return {
    confirmation_code: res.confirmation_code,
    reservation: ReservationSchema.parse(res),
  };
});

const ModifyRequestSchema = z.object({
  confirmation_code: z.string().min(1),
  idempotency_key: z.string().min(1),
  changes: z.object({
    start_local: z.string().regex(/^\d{2}:\d{2}$/).optional(),
    players: z.number().int().min(1).max(4).optional(),
  }),
});

app.post("/v1/tools/modify-reservation", async (req, reply) => {
  requireAuth(req);
  if (env.DEMO_READ_ONLY) {
    reply.code(403);
    return { error: "Demo is in read-only mode" };
  }

  const parsed = ModifyRequestSchema.safeParse(req.body);
  if (!parsed.success) {
    reply.code(400);
    return { error: "Invalid request", details: parsed.error.flatten() };
  }

  const existing = reservations.get(parsed.data.confirmation_code);
  if (!existing) {
    reply.code(404);
    return { error: "Reservation not found" };
  }

  const updated = reservations.modify(parsed.data.confirmation_code, parsed.data.changes);
  if (!updated) {
    reply.code(404);
    return { error: "Reservation not found" };
  }

  return { confirmation_code: updated.confirmation_code, reservation: ReservationSchema.parse(updated) };
});

const CancelRequestSchema = z.object({
  confirmation_code: z.string().min(1),
  idempotency_key: z.string().min(1),
});

app.post("/v1/tools/cancel-reservation", async (req, reply) => {
  requireAuth(req);
  if (env.DEMO_READ_ONLY) {
    reply.code(403);
    return { error: "Demo is in read-only mode" };
  }

  const parsed = CancelRequestSchema.safeParse(req.body);
  if (!parsed.success) {
    reply.code(400);
    return { error: "Invalid request", details: parsed.error.flatten() };
  }

  const updated = reservations.cancel(parsed.data.confirmation_code);
  if (!updated) {
    reply.code(404);
    return { error: "Reservation not found" };
  }

  return {
    confirmation_code: updated.confirmation_code,
    status: updated.status,
    cancelled_at: updated.cancelled_at,
    policy: {
      fee_applied: false,
      message: "Cancelled successfully.",
    },
  };
});

app.setErrorHandler((err, _req, reply) => {
  const status = (err as any).statusCode ?? 500;
  reply.code(status).send({ error: err.message ?? "Internal Server Error" });
});

async function main() {
  await app.listen({ host: "0.0.0.0", port: env.DEMO_BACKEND_PORT });
  app.log.info(`demo-backend listening on :${env.DEMO_BACKEND_PORT}`);
}

main().catch((e) => {
  // eslint-disable-next-line no-console
  console.error(e);
  process.exit(1);
});
