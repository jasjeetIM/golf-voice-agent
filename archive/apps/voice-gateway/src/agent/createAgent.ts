import * as Agents from '@openai/agents';
import { BackendClient } from '../integrations/backend/client.js';
import { systemPrompt } from './prompts/system.js';
import { policyRules } from './prompts/policies.js';
import { searchTeeTimesTool } from './tools/searchTeeTimes.js';
import { bookTeeTimeTool } from './tools/bookTeeTime.js';
import { modifyReservationTool } from './tools/modifyReservation.js';
import { cancelReservationTool } from './tools/cancelReservation.js';
import { sendSmsConfirmationTool } from './tools/sendSmsConfirmation.js';
import { getReservationDetailsTool } from './tools/getReservationDetails.js';
import { quoteReservationChangeTool } from './tools/quoteReservationChange.js';
import { checkSlotCapacityTool } from './tools/checkSlotCapacity.js';

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
    getReservationDetailsTool(client),
    quoteReservationChangeTool(client),
    checkSlotCapacityTool(client),
  ];

  const policyTextParts: string[] = [];
  if (policyRules.requireFields?.length) {
    policyTextParts.push(`Always collect: ${policyRules.requireFields.join(', ')}.`);
  }
  if (policyRules.forbidPayment) {
    policyTextParts.push('Never ask for payment or credit card details.');
  }
  const today = new Date().toISOString().slice(0, 10);
  const instructions = [
    `Today is ${today}. Use this to resolve relative dates (e.g., "tomorrow", "next Friday") into ISO dates.`,
    systemPrompt,
    policyTextParts.join(' '),
  ].join('\n');

  return new RealtimeAgent({
    apiKey: opts.apiKey,
    model: opts.model,
    instructions,
    voice: opts.voice ?? { name: 'alloy' },
    turnDetection: opts.turnDetection ?? { type: 'server_vad' },
    tools,
  });
}
