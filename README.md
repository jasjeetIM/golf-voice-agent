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
| voice-gateway     |
| (realtime edge)   |
+-------------------+
|
| HTTP (tool calls)
v
+-------------------+
| backend           |
| (domain + DB)     |
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
├── python/                 # Python port (active)
│   ├── backend/            # Domain logic + PostgreSQL
│   ├── voice_gateway/      # Realtime edge service (Twilio + RealtimeAgent)
│   └── shared/             # Shared schemas
├── archive/                # Archived TypeScript implementation
└── README.md

---

## Services (Python)

### voice_gateway

Handles:

- Incoming Twilio calls
- Media streaming via WebSockets
- STT → LLM → TTS agent loop (OpenAI Realtime)
- Tool invocation via MCP-backed tools

### backend

Handles:

- Reservation and tee-time inventory logic
- PostgreSQL schema and transactions
- Audit logs and call observability
- Notification outbox (SMS/email)

---

## Getting Started

See the Python README:

- `python/README.md`

---

## Archive

The original TypeScript implementation has been moved to:

- `archive/`
