import { tool } from "@openai/agents";
import {
  SendSmsConfirmationRequestSchema,
  SendSmsConfirmationResponseSchema,
  SendSmsConfirmationRequest,
} from "@golf/shared-schemas";
import { BackendClient } from "../../integrations/backend/client.js";

export function sendSmsConfirmationTool(client: BackendClient) {
  return tool({
    name: "send_sms_confirmation",
    description: "Send an SMS confirmation for a booking to the provided phone number.",
    parameters: SendSmsConfirmationRequestSchema,
    strict: true,
    execute: async (input: SendSmsConfirmationRequest) =>
      SendSmsConfirmationResponseSchema.parse(await client.sendSmsConfirmation(input)),
  });
}
