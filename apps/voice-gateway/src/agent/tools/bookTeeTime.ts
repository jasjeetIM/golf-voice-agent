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
    description:
      "Book a tee time once the caller has confirmed date, time, players, walking/riding preference, and contact info.",
    parameters: BookTeeTimeRequestSchema,
    strict: true,
    execute: async (input: BookTeeTimeRequest) =>
      BookTeeTimeResponseSchema.parse(await client.bookTeeTime(input)),
  });
}
