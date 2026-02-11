import { tool } from '@openai/agents';
import {
  QuoteReservationChangeRequestSchema,
  QuoteReservationChangeResponseSchema,
  QuoteReservationChangeRequest,
} from '@golf/shared-schemas';
import { BackendClient } from '../../integrations/backend/client.js';

export function quoteReservationChangeTool(client: BackendClient) {
  return tool({
    name: 'quote_reservation_change',
    description:
      'Check if a proposed change (new slot, players, or type) is possible before modifying a reservation.',
    parameters: QuoteReservationChangeRequestSchema,
    strict: true,
    execute: async (input: QuoteReservationChangeRequest) =>
      QuoteReservationChangeResponseSchema.parse(await client.quoteReservationChange(input)),
  });
}
