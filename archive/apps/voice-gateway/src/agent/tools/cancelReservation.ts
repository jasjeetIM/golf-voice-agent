import { tool } from '@openai/agents';
import {
  CancelReservationRequestSchema,
  CancelReservationResponseSchema,
  CancelReservationRequest,
} from '@golf/shared-schemas';
import { BackendClient } from '../../integrations/backend/client.js';

export function cancelReservationTool(client: BackendClient) {
  return tool({
    name: 'cancel_reservation',
    description:
      "Cancel an existing reservation using the confirmation code and the caller's contact confirmation.",
    parameters: CancelReservationRequestSchema,
    strict: true,
    execute: async (input: CancelReservationRequest) =>
      CancelReservationResponseSchema.parse(await client.cancelReservation(input)),
  });
}
