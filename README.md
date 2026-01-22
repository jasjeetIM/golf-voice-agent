# Golf Voice Agent

A real-time voice-based golf reservation system that allows customers to book, modify, and cancel tee times over the phone using a conversational AI agent.

The system integrates:
- Twilio (PSTN + Media Streams)
- Real-time speech-to-text and text-to-speech
- A tool-using LLM agent
- A PostgreSQL-backed reservation system
- SMS/email confirmations

The architecture prioritizes **correctness, debuggability, and scalability**, while remaining cloud-native and compliant with 12-factor principles.

---

## High-Level Architecture

Twilio (PSTN + Media Streams)
|
v
+-------------------+
| voice-gateway |
| (realtime edge) |
+-------------------+
|
| HTTP (tool calls)
v
+-------------------+
| backend |
| (domain + DB) |
+-------------------+
|
v
PostgreSQL

### Design Principles

- **Separation of concerns**
  - Realtime audio + agent orchestration is isolated from database logic
- **Strong transactional guarantees**
  - No double booking
  - Safe retries and idempotency
- **Observability-first**
  - Every call and action is traceable
- **12-factor compliant**
  - Stateless services
  - Backing services treated as attached resources

---

## Repository Structure

.
├── apps/
│ ├── voice-gateway/ # Realtime edge service (Twilio + Agent)
│ └── backend/ # Domain logic + PostgreSQL
├── packages/ # Shared types/utilities (if applicable)
└── README.md

---

## Services

### voice-gateway
Handles:
- Incoming Twilio calls
- Media streaming via WebSockets
- STT → LLM → TTS agent loop
- Tool invocation (HTTP calls to backend)

See: `apps/voice-gateway/README.md`

### backend
Handles:
- Reservation and tee-time inventory logic
- PostgreSQL schema and transactions
- Audit logs and call observability
- Notification outbox (SMS/email)

See: `apps/backend/README.md`

---

## Deployment Model

- Each service is independently deployable
- Scales horizontally
- No shared in-memory state
- Environment-variable driven configuration

---

## Getting Started

Quick start (after `pnpm install`):
- Backend: `pnpm --filter @golf/backend run dev`
- Gateway: `pnpm --filter @golf/voice-gateway run dev`

Dotenv hints:
- Core: `PUBLIC_HOST`, `PUBLIC_PROTOCOL`, `VOICE_GATEWAY_PORT`, `BACKEND_PORT`
- Gateway: `OPENAI_API_KEY`, `BACKEND_API_KEY`, `LOG_LEVEL` (derives URLs from host/ports)
- Backend: `DB_CONNECTION_STRING`, `DB_SSL`, `DB_POOL_MAX`, `DB_READ_ONLY`, `BACKEND_API_KEY`

For more, see:
- `apps/voice-gateway/README.md`
- `apps/backend/README.md`
