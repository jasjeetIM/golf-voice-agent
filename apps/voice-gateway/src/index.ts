import Fastify from "fastify";
import dotenv from "dotenv";
import { WebSocketServer, WebSocket } from "ws";

import { TwilioMediaStreamEventSchema } from "@golf/shared-schemas";

import { loadEnv } from "./config/env.js";
import { createLogger } from "./observability/logger.js";
import { buildConnectStreamTwiML } from "./ws/twilio/twiml.js";
import { DemoBackendClient } from "./integrations/demoBackend/client.js";

dotenv.config();

const env = loadEnv(process.env);
const logger = createLogger(env.LOG_LEVEL);

const app = Fastify({
  logger,
});

const demoBackend = new DemoBackendClient({
  baseUrl: env.DEMO_BACKEND_URL,
  apiKey: env.DEMO_API_KEY,
});

app.get("/health", async () => ({ status: "ok", service: "voice-gateway" }));

// Simple route to validate gateway -> demo-backend connectivity
app.get("/demo/search", async () => {
  const resp = await demoBackend.searchTeeTimes({
    course_id: "demo_course",
    date: "2026-02-21",
    time_window: { start_local: "08:00", end_local: "11:00" },
    players: 4,
    holes: 18,
    walking_preference: "either",
    max_results: 5,
  });
  return resp;
});

// Twilio webhook: returns TwiML that starts Media Streams
app.post("/twilio/inbound", async (_req, reply) => {
  const wsUrl = `${env.PUBLIC_BASE_URL.replace(/^http/, "ws")}/twilio/stream`;
  const twiml = buildConnectStreamTwiML(wsUrl);

  reply.header("Content-Type", "text/xml");
  return twiml;
});

async function main() {
  await app.listen({ host: "0.0.0.0", port: env.VOICE_GATEWAY_PORT });
  app.log.info(`voice-gateway listening on :${env.VOICE_GATEWAY_PORT}`);

  const wss = new WebSocketServer({ server: app.server, path: "/twilio/stream" });

  wss.on("connection", (socket: WebSocket) => {
    app.log.info("Twilio WS connected");

    socket.on("message", (data) => {
      try {
        const raw = data.toString("utf8");
        const parsedJson = JSON.parse(raw);
        const parsed = TwilioMediaStreamEventSchema.safeParse(parsedJson);

        if (!parsed.success) {
          app.log.warn({ err: parsed.error.flatten() }, "Invalid Twilio event");
          return;
        }

        const evt = parsed.data;
        if (evt.event === "start") {
          app.log.info({ callSid: evt.start.callSid, streamSid: evt.start.streamSid }, "Twilio start");
        } else if (evt.event === "media") {
          app.log.debug({ track: evt.media.track }, "Twilio media");
        } else if (evt.event === "mark") {
          app.log.info({ name: evt.mark.name }, "Twilio mark");
        } else if (evt.event === "stop") {
          app.log.info("Twilio stop");
        }
      } catch (e) {
        app.log.warn({ err: e }, "Error handling Twilio WS message");
      }
    });

    socket.on("close", () => {
      app.log.info("Twilio WS closed");
    });
  });
}

main().catch((e) => {
  // eslint-disable-next-line no-console
  console.error(e);
  process.exit(1);
});
