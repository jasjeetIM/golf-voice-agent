# voice-gateway

The **voice-gateway** is the realtime edge service for the Golf Voice Agent.

It handles:
- Incoming phone calls from Twilio
- WebSocket media streams
- Running the conversational AI agent
- Invoking backend tools over HTTP

This service is **latency-sensitive** and **stateless** by design.

---

## Responsibilities

### What this service does
- Accepts Twilio webhooks for inbound calls
- Establishes Twilio Media Streams (WebSocket)
- Runs the STT → LLM → TTS loop
- Maintains ephemeral, in-memory session state
- Calls backend tools to perform business actions
- Emits call events for observability

### What this service does *not* do
- No direct database access
- No business rule enforcement
- No reservation correctness logic

All persistent state lives in the backend service.

---

## Key Concepts

### Agent Session
Each call creates an isolated agent session that:
- Maintains conversational context
- Decides which tools to invoke
- Streams audio responses back to the caller

Session state is **in-memory only** and discarded when the call ends.

### Tool Invocation
The agent interacts with the backend exclusively via tools, such as:
- `bookTeeTime`
- `modifyReservation`
- `cancelReservation`
- `searchTeeTimes`

Tools are HTTP APIs implemented by the backend.

---

## Directory Structure

src/
├── agent/             # Agent configuration, prompts, tools, guardrails
├── config/            # Env parsing, constants
├── http/              # Fastify server + routes (Twilio inbound, health)
│   └── routes/
├── ws/                # WebSocket handling (Twilio Media Streams)
│   └── twilio/
├── integrations/      # Backend HTTP client, OpenAI transport
│   └── backend/
├── observability/     # Logging/tracing hooks
├── utils/             # IDs, time, phone helpers
└── index.ts           # Bootstrap

---

## Configuration

All configuration is provided via environment variables.

Common examples:
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `BACKEND_BASE_URL`
- `OPENAI_API_KEY`

No configuration is hardcoded.

---

## Scaling Characteristics

- Scales by **concurrent calls**
- Instances are disposable
- No sticky sessions required
- Safe to autoscale

---

## Failure Model

- If backend is unavailable, calls fail gracefully
- No partial reservation state is stored here
- Retries are safe because backend tools are idempotent

---

## Why No Database Here?

Keeping the gateway DB-free:
- Reduces blast radius
- Keeps latency predictable
- Simplifies scaling
- Improves security posture

This service should be boring, fast, and replaceable.