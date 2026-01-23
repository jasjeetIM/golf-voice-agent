import { z } from "zod";
import { SearchTeeTimesRequestSchema, SearchTeeTimesResponseSchema } from "./searchTeeTimes.js";

export const ListAvailableSlotsRequestSchema = SearchTeeTimesRequestSchema;
export const ListAvailableSlotsResponseSchema = SearchTeeTimesResponseSchema;

export type ListAvailableSlotsRequest = z.infer<typeof ListAvailableSlotsRequestSchema>;
export type ListAvailableSlotsResponse = z.infer<typeof ListAvailableSlotsResponseSchema>;
