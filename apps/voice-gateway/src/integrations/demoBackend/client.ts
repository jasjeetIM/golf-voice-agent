import { request } from "undici";
import {
  SearchTeeTimesRequest,
  SearchTeeTimesResponseSchema,
  SearchTeeTimesRequestSchema,
} from "@golf/shared-schemas";

export type DemoBackendClientConfig = {
  baseUrl: string;
  apiKey: string;
};

export class DemoBackendClient {
  constructor(private cfg: DemoBackendClientConfig) {}

  async searchTeeTimes(req: SearchTeeTimesRequest) {
    // Validate input early
    const validated = SearchTeeTimesRequestSchema.parse(req);

    const url = `${this.cfg.baseUrl}/v1/tools/search-tee-times`;
    const res = await request(url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "authorization": `Bearer ${this.cfg.apiKey}`,
      },
      body: JSON.stringify(validated),
    });

    const bodyText = await res.body.text();
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw new Error(`demo-backend error ${res.statusCode}: ${bodyText}`);
    }

    const json = JSON.parse(bodyText);
    return SearchTeeTimesResponseSchema.parse(json);
  }
}
