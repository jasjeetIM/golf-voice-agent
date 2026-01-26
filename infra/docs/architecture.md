# Architecture Overview

This system is a realtime, voice-first tee time agent. Twilio Media Streams deliver audio to a WebSocket gateway, which hosts an OpenAI Realtime agent. The agent drives tool calls into a backend that owns business logic, persistence, and observability.

## Voice Gateway (apps/voice-gateway)

- **Inbound call → TwiML → WS upgrade.** Twilio hits `POST /twilio/inbound` (Fastify route `http/routes/twilio.inbound.ts`). We return TwiML that connects a Media Stream to `wss://.../twilio/stream`. The HTTP server (see `ws/server.ts`) listens for `upgrade` events and upgrades requests on `/twilio/stream` into WebSocket connections.
- **Session wiring.** Each upgraded socket is handed to `handleTwilioSession` (`ws/twilio/twilioSession.ts`). It builds a `TwilioRealtimeTransportLayer`, creates the Realtime agent via `createAgent` (`agent/createAgent.ts`), and starts an agent session (`agent/session.ts`) with event logging.
- **Agent creation.** `createAgent` wraps `@openai/agents` with:
  - **Tools** (search, book, modify, cancel, SMS) defined under `agent/tools/*`. Each tool uses Zod schemas, `strict: true`, and descriptive names so the model knows when to invoke them.
  - **Backend client** (`integrations/backend/client.ts`) injected into tools; it signs requests with `BACKEND_API_KEY` and parses responses.
  - **Prompts/policies** (`agent/prompts/system.ts`, `policies.ts`) to enforce required fields, confirmation codes, and no-payment rules.
- **Message validation.** Incoming Twilio WS messages are Zod-validated (`ws/twilio/twilioMessages.ts`) before being given to the transport; invalid frames are rejected early.
- **Observability.** `agent/session.ts` emits `tool_call`, `tool_result`, transcripts, and errors to the logger; logs include `callSid/streamSid` for correlation. (Additional tracing/logging hooks live in `observability/*`.)

## Backend (apps/backend)

- **Server.** Fastify server (`http/server.ts`) exposes `POST /v1/tools/*` endpoints. It constructs domain services: `InventoryStore` (read availability) and `ReservationStore` (book/modify/cancel, not shown here).
- **Auth.** Each tool route checks `Authorization: Bearer ${BACKEND_API_KEY}` before executing.
- **Persistence.** Postgres schema (`db/migrations/0001_init.sql`) models customers, courses, tee time slots, reservations, and all call-related telemetry (`calls`, `call_events`, `agent_messages`, `tool_calls`, `notifications_outbox`). This supports auditing, idempotency, and replayability.
- **Inventory flow.** `InventoryStore.search` queries `tee_time_slots` with time-window, capacity, and pricing logic, returning normalized `TeeTimeOption`s. Reservation operations use transactional helpers in `db/tx.ts` and `pool.ts` (typed `PoolClient` access).
- **Tool HTTP handlers.** Under `http/routes/tools/*`, each endpoint validates with the shared Zod schemas from `@golf/shared-schemas`, calls the corresponding store method, and returns typed responses. Examples:
  - `search-tee-times` → availability lookup
  - `book-tee-time` → create reservation + change log
  - `modify-reservation`, `cancel-reservation` → update with idempotency tracking
  - `send-sms-confirmation` → enqueue notification

## Backend Client + Agent Tools

- **Backend client design.** `integrations/backend/client.ts` is a thin, typed HTTP client that:
  1. Parses inputs with Zod request schemas.
  2. POSTs JSON with bearer auth to `/v1/tools/...`.
  3. Parses responses with Zod response schemas, throwing on non-2xx.
- **Tool invocation.** Each tool in `agent/tools/*` captures one backend call and forwards the client. Example: `search_tee_times` passes the already-validated input to `client.searchTeeTimes`, returning the validated response. Tools are marked `strict: true`, so the Realtime runtime enforces argument shape before execution.
- **End-to-end flow.** Caller speaks → Twilio WS frames → Realtime agent receives transcripts/audio → Agent selects a tool (e.g., `search_tee_times`) based on system prompt and tool descriptions → Tool executes via backend client → Backend validates/authenticates, hits Postgres → Result is returned to the agent → Agent responds to the caller or chains further tool calls (book/modify/cancel/SMS).

## Key Design Principles

- **Separation of concerns:** Voice gateway handles transport + agent orchestration; backend owns business logic and state.
- **Schema-first:** Zod schemas shared across agent tools, backend client, and backend handlers guarantee consistent validation at every hop.
- **Auditability:** Database schema captures calls, messages, tool invocations, and notifications for debugging and analytics.
- **Explicit contracts:** Tool descriptions and strict schemas make model tool-choice reliable; system/policy prompts constrain behavior (required fields, confirmation codes, no payments).
- **Operational clarity:** WS upgrade path is narrow (`/twilio/stream`), and HTTP tool endpoints are authenticated and versioned (`/v1/tools/*`) for safe evolution.
