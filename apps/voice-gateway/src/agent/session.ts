import * as Agents from "@openai/agents";
import type { TwilioRealtimeTransportLayer } from "@openai/agents-extensions";

const RealtimeSession: any = (Agents as any).RealtimeSession;
type RealtimeAgent = any;

type SessionDeps = {
  agent: RealtimeAgent;
  transport: TwilioRealtimeTransportLayer;
  callSid?: string;
  logger?: (evt: string, payload?: Record<string, unknown>) => void;
};

export function createAgentSession({ agent, transport, callSid, logger }: SessionDeps) {
  const session = new RealtimeSession({
    agent,
    transports: [transport],
  });

  const log = logger ?? (() => undefined);

  session.on("partial_transcript", (payload: any) => log("partial_transcript", { callSid, ...payload }));
  session.on("final_transcript", (payload: any) => log("final_transcript", { callSid, ...payload }));
  session.on("tool_call", (payload: any) => log("tool_call", { callSid, ...payload }));
  session.on("tool_result", (payload: any) => log("tool_result", { callSid, ...payload }));
  session.on("interruption", (payload: any) => log("interruption", { callSid, ...payload }));
  session.on("error", (payload: any) => log("error", { callSid, ...payload }));

  return session;
}
