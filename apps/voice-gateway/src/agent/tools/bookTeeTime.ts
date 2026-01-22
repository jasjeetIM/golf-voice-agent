import { tool } from "@openai/agents";
import {
  BookTeeTimeRequestSchema,
  BookTeeTimeResponseSchema,
  BookTeeTimeRequest,
} from "@golf/shared-schemas";
import { BackendClient } from "../../integrations/backend/client.js";

export function bookTeeTimeTool(client: BackendClient) {
  return tool({
    name: "book_tee_time",
    description: "Book a tee time after confirming date, time, players, and contact.",
    schema: BookTeeTimeRequestSchema,
    execute: async (args: BookTeeTimeRequest) => {
      const result = await client.bookTeeTime(args);
      return BookTeeTimeResponseSchema.parse(result);
    },
  });
}
