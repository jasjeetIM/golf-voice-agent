import { tool } from '@openai/agents';
import {
  SearchTeeTimesRequestSchema,
  SearchTeeTimesResponseSchema,
  SearchTeeTimesRequest,
} from '@golf/shared-schemas';
import { BackendClient } from '../../integrations/backend/client.js';

export function searchTeeTimesTool(client: BackendClient) {
  return tool({
    name: 'search_tee_times',
    description:
      'Search available tee times for a course on a specific date and time window with player count and WALKING/RIDING preference.',
    parameters: SearchTeeTimesRequestSchema,
    strict: true,
    execute: async (input: SearchTeeTimesRequest) =>
      SearchTeeTimesResponseSchema.parse(await client.searchTeeTimes(input)),
  });
}
