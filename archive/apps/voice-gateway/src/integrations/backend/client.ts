import { request } from 'undici';
import {
  SearchTeeTimesRequest,
  SearchTeeTimesResponseSchema,
  SearchTeeTimesRequestSchema,
  BookTeeTimeRequest,
  BookTeeTimeRequestSchema,
  BookTeeTimeResponseSchema,
  ModifyReservationRequest,
  ModifyReservationRequestSchema,
  ModifyReservationResponseSchema,
  CancelReservationRequest,
  CancelReservationRequestSchema,
  CancelReservationResponseSchema,
  SendSmsConfirmationRequest,
  SendSmsConfirmationRequestSchema,
  SendSmsConfirmationResponseSchema,
  GetReservationDetailsRequest,
  GetReservationDetailsRequestSchema,
  GetReservationDetailsResponseSchema,
  QuoteReservationChangeRequest,
  QuoteReservationChangeRequestSchema,
  QuoteReservationChangeResponseSchema,
  CheckSlotCapacityRequest,
  CheckSlotCapacityRequestSchema,
  CheckSlotCapacityResponseSchema,
} from '@golf/shared-schemas';

export type BackendClientConfig = {
  baseUrl: string;
  apiKey: string;
};

export class BackendClient {
  constructor(private cfg: BackendClientConfig) {}

  private async postAndParse<T>(
    path: string,
    body: unknown,
    schema: { parse(data: unknown): T }
  ): Promise<T> {
    const url = `${this.cfg.baseUrl}${path}`;
    const res = await request(url, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        authorization: `Bearer ${this.cfg.apiKey}`,
      },
      body: JSON.stringify(body),
    });

    const bodyText = await res.body.text();
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw new Error(`backend error ${res.statusCode}: ${bodyText}`);
    }

    const json = JSON.parse(bodyText);
    return schema.parse(json);
  }

  async searchTeeTimes(req: SearchTeeTimesRequest) {
    const validated = SearchTeeTimesRequestSchema.parse(req);
    return this.postAndParse('/v1/tools/search-tee-times', validated, SearchTeeTimesResponseSchema);
  }

  async bookTeeTime(req: BookTeeTimeRequest) {
    const validated = BookTeeTimeRequestSchema.parse(req);
    return this.postAndParse('/v1/tools/book-tee-time', validated, BookTeeTimeResponseSchema);
  }

  async modifyReservation(req: ModifyReservationRequest) {
    const validated = ModifyReservationRequestSchema.parse(req);
    return this.postAndParse(
      '/v1/tools/modify-reservation',
      validated,
      ModifyReservationResponseSchema
    );
  }

  async cancelReservation(req: CancelReservationRequest) {
    const validated = CancelReservationRequestSchema.parse(req);
    return this.postAndParse(
      '/v1/tools/cancel-reservation',
      validated,
      CancelReservationResponseSchema
    );
  }

  async sendSmsConfirmation(req: SendSmsConfirmationRequest) {
    const validated = SendSmsConfirmationRequestSchema.parse(req);
    return this.postAndParse(
      '/v1/tools/send-sms-confirmation',
      validated,
      SendSmsConfirmationResponseSchema
    );
  }

  async getReservationDetails(req: GetReservationDetailsRequest) {
    const validated = GetReservationDetailsRequestSchema.parse(req);
    return this.postAndParse(
      '/v1/tools/get-reservation-details',
      validated,
      GetReservationDetailsResponseSchema
    );
  }

  async quoteReservationChange(req: QuoteReservationChangeRequest) {
    const validated = QuoteReservationChangeRequestSchema.parse(req);
    return this.postAndParse(
      '/v1/tools/quote-reservation-change',
      validated,
      QuoteReservationChangeResponseSchema
    );
  }

  async checkSlotCapacity(req: CheckSlotCapacityRequest) {
    const validated = CheckSlotCapacityRequestSchema.parse(req);
    return this.postAndParse(
      '/v1/tools/check-slot-capacity',
      validated,
      CheckSlotCapacityResponseSchema
    );
  }
}
