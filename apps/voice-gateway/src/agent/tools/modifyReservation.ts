import { tool } from "@openai/agents";
import {
  ModifyReservationRequestSchema,
  ModifyReservationResponseSchema,
  ModifyReservationRequest,
} from "@golf/shared-schemas";
import { BackendClient } from "../../integrations/backend/client.js";

export function modifyReservationTool(client: BackendClient) {
  return tool({
    name: "modify_reservation",
    description: "Modify a reservation (time or players) using the confirmation code.",
    schema: ModifyReservationRequestSchema,
    execute: async (args: ModifyReservationRequest) => {
      const result = await client.modifyReservation(args);
      return ModifyReservationResponseSchema.parse(result);
    },
  });
}
