import { tool } from '@openai/agents';
import {
  CheckSlotCapacityRequestSchema,
  CheckSlotCapacityResponseSchema,
  CheckSlotCapacityRequest,
} from '@golf/shared-schemas';
import { BackendClient } from '../../integrations/backend/client.js';

export function checkSlotCapacityTool(client: BackendClient) {
  return tool({
    name: 'check_slot_capacity',
    description: 'Check if a specific slot_id has capacity for the desired number of players.',
    parameters: CheckSlotCapacityRequestSchema,
    strict: true,
    execute: async (input: CheckSlotCapacityRequest) =>
      CheckSlotCapacityResponseSchema.parse(await client.checkSlotCapacity(input)),
  });
}
