import { tool } from "@openai/agents";
import {
  CancelReservationRequestSchema,
  CancelReservationResponseSchema,
  CancelReservationRequest,
} from "@golf/shared-schemas";
import { BackendClient } from "../../integrations/backend/client.js";

export function cancelReservationTool(client: BackendClient) {
  return tool({
    name: "cancel_reservation",
    description: "Cancel an existing reservation using the confirmation code.",
    schema: CancelReservationRequestSchema,
    execute: async (args: CancelReservationRequest) => {
      const result = await client.cancelReservation(args);
      return CancelReservationResponseSchema.parse(result);
    },
  });
}
