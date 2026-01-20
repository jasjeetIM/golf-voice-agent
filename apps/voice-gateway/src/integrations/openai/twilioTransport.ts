import { TwilioRealtimeTransportLayer } from "@openai/agents-extensions";
import type WebSocket from "ws";

// Wrap the OpenAI extension that bridges Twilio Media Streams to Realtime
export function createTwilioTransport(connection: WebSocket) {
  // The typings may not expose the raw socket option; cast to any to allow passing the WS connection.
  return new TwilioRealtimeTransportLayer({
    connection,
    enableMarkEvents: true,
  } as any);
}
