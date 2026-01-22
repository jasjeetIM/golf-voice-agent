import * as Agents from "@openai/agents";
import { BackendClient } from "../integrations/backend/client.js";
import { systemPrompt } from "./prompts/system.js";
import { policyRules } from "./prompts/policies.js";
import { searchTeeTimesTool } from "./tools/searchTeeTimes.js";
import { bookTeeTimeTool } from "./tools/bookTeeTime.js";
import { modifyReservationTool } from "./tools/modifyReservation.js";
import { cancelReservationTool } from "./tools/cancelReservation.js";
import { sendSmsConfirmationTool } from "./tools/sendSmsConfirmation.js";

type AgentOptions = {
  apiKey: string;
  model: string;
  backendBaseUrl: string;
  backendApiKey: string;
  voice?: { name: string };
  turnDetection?: any;
};

export function createAgent(opts: AgentOptions): any {
  const RealtimeAgent: any = (Agents as any).RealtimeAgent;
  const client = new BackendClient({
    baseUrl: opts.backendBaseUrl,
    apiKey: opts.backendApiKey,
  });

  const tools = [
    searchTeeTimesTool(client),
    bookTeeTimeTool(client),
    modifyReservationTool(client),
    cancelReservationTool(client),
    sendSmsConfirmationTool(client),
  ];

  const policyTextParts: string[] = [];
  if (policyRules.requireFields?.length) {
    policyTextParts.push(`Always collect: ${policyRules.requireFields.join(", ")}.`);
  }
  if (policyRules.forbidPayment) {
    policyTextParts.push("Never ask for payment or credit card details.");
  }
  const instructions = [systemPrompt, policyTextParts.join(" ")].join("\n");

  return new RealtimeAgent({
    apiKey: opts.apiKey,
    model: opts.model,
    instructions,
    voice: opts.voice ?? { name: "alloy" },
    turnDetection: opts.turnDetection ?? { type: "server_vad" },
    tools,
  });
}
