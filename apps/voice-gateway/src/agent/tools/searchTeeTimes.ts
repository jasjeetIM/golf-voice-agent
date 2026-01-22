import { tool } from "@openai/agents";
import {
  SearchTeeTimesRequestSchema,
  SearchTeeTimesResponseSchema,
  SearchTeeTimesRequest,
} from "@golf/shared-schemas";
import { BackendClient } from "../../integrations/backend/client.js";

export function searchTeeTimesTool(client: BackendClient) {
  return tool({
    name: "search_tee_times",
    description: "Search available tee times for a given date and player count.",
    schema: SearchTeeTimesRequestSchema,
    execute: async (args: SearchTeeTimesRequest) => {
      const result = await client.searchTeeTimes(args);
      return SearchTeeTimesResponseSchema.parse(result);
    },
  });
}
