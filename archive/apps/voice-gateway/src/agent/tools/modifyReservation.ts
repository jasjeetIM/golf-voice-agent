import { tool } from '@openai/agents';
import {
  ModifyReservationRequestSchema,
  ModifyReservationResponseSchema,
  ModifyReservationRequest,
} from '@golf/shared-schemas';
import { BackendClient } from '../../integrations/backend/client.js';

export function modifyReservationTool(client: BackendClient) {
  return tool({
    name: 'modify_reservation',
    description:
      'Modify a reservation (time or player count) using the confirmation code and updated details provided by the caller.',
    parameters: ModifyReservationRequestSchema,
    strict: true,
    execute: async (input: ModifyReservationRequest) =>
      ModifyReservationResponseSchema.parse(await client.modifyReservation(input)),
  });
}
