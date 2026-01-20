import type { IncomingMessage } from "http";
import type WebSocket from "ws";
import { createTwilioTransport } from "../../integrations/openai/twilioTransport";
import { parseTwilioMessage } from "./twilioMessages";

// Per-call session lifecycle: wire Twilio Media Stream WS to the OpenAI transport
export function handleTwilioSession(ws: WebSocket, req: IncomingMessage) {
  const transport = createTwilioTransport(ws);
}
