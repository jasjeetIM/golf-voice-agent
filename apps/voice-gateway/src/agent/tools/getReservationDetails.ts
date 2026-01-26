import { tool } from '@openai/agents';
import {
  GetReservationDetailsRequestSchema,
  GetReservationDetailsResponseSchema,
  GetReservationDetailsRequest,
} from '@golf/shared-schemas';
import { BackendClient } from '../../integrations/backend/client.js';

export function getReservationDetailsTool(client: BackendClient) {
  return tool({
    name: 'get_reservation_details',
    description:
      'Fetch reservation details by confirmation code to confirm current time, players, and type.',
    parameters: GetReservationDetailsRequestSchema,
    strict: true,
    execute: async (input: GetReservationDetailsRequest) =>
      GetReservationDetailsResponseSchema.parse(await client.getReservationDetails(input)),
  });
}
