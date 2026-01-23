import type { IncomingMessage } from "http";
import type WebSocket from "ws";
import { createTwilioTransport } from "../../integrations/openai/twilioTransport.js";
import { parseTwilioMessage } from "./twilioMessages.js";
import { createAgent } from "../../agent/createAgent.js";
import { createAgentSession } from "../../agent/session.js";
import { loadEnv } from "../../config/env.js";

// Per-call session lifecycle: wire Twilio Media Stream WS to the OpenAI transport and agent session
export function handleTwilioSession(ws: WebSocket, _req: IncomingMessage) {
  const env = loadEnv(process.env);
  let callSid: string | undefined;
  let streamSid: string | undefined;

  const transport = createTwilioTransport(ws);
  const agent = createAgent({
    apiKey: env.OPENAI_API_KEY,
    model: "gpt-4o-realtime-preview-2024-12-17",
    backendBaseUrl: env.backend_url,
    backendApiKey: env.BACKEND_API_KEY,
    voice: { name: "cove" },
    turnDetection: { type: "server_vad" },
  });

  const session = createAgentSession({
    agent,
    transport,
    logger: (evt, payload) =>
      console.log(JSON.stringify({ evt, callSid, streamSid, ...payload })),
  });

  ws.on("message", (raw) => {
    try {
      const event = parseTwilioMessage(raw.toString());
      if (event.event === "start") {
        callSid = event.start.callSid;
        streamSid = event.start.streamSid;
      }
      // Transport handles media internally; no manual forwarding unless API changes.
    } catch (err) {
      console.error("Failed to parse Twilio message", err);
    }
  });

  ws.on("close", () => {
    session.close?.();
    (transport as any).close?.();
  });
}
