# backend

The **backend** service owns all business logic and persistent state for the Golf Voice Agent.

It is the **single source of truth** for:
- Tee time inventory
- Reservations
- Audit history
- Call observability
- Notifications

---

## Responsibilities

### What this service does
- Owns PostgreSQL schema and migrations
- Enforces transactional correctness
- Implements reservation lifecycle:
  - create
  - modify (time, party size, round type)
  - cancel
- Records immutable audit logs
- Stores call and agent telemetry
- Manages SMS/email outbox

### What this service does *not* do
- ❌ No realtime audio streaming
- ❌ No STT/TTS or agent orchestration

---

## Database Design Overview

The database is split into:

### Current State Tables
- `customers`
- `courses`
- `tee_time_slots`
- `reservations`
- `calls`

These represent **what is true right now**.

### Append-Only / Audit Tables
- `reservation_changes`
- `call_events`
- `agent_messages`
- `tool_calls`
- `call_reservations`

These represent **what happened and when**.

### Outbox
- `notifications_outbox`

Used for reliable SMS/email delivery.

---

## Key Domain Concepts

### Tee Time Slots
- Identified by `course_id + start_ts`
- No duration
- Capacity-based (`capacity_players`)
- Multiple reservations may share a slot until capacity is full

### Reservations
- Store only:
  - `start_ts`
  - `round_type` (`NINE` / `EIGHTEEN`)
- Linked to a tee time slot
- Never deleted — only canceled

### Audit Trail
Every reservation mutation produces:
- One row update in `reservations`
- One immutable row in `reservation_changes`

Both occur in the same transaction.

---

## Directory Structure

src/
├── db/
│   ├── pool.ts          # PostgreSQL connection pool
│   ├── tx.ts            # Transaction helper
│   ├── migrations/      # SQL migrations
│   └── repositories/    # Data access logic
├── services/
│   ├── reservations.ts  # Booking/modification logic
│   ├── inventory.ts     # Slot search and rules
│   └── notifications.ts # Outbox handling
├── http/
│   └── routes/
│       └── tools/       # Tool endpoints
├── config/              # Env parsing
├── observability/       # Logging, request IDs
└── index.ts


---

## Transactions & Idempotency

- All reservation mutations run inside a DB transaction
- Tee time slots are locked (`SELECT ... FOR UPDATE`)
- Capacity is enforced at commit time
- Each mutation requires an `idempotency_key`
- Safe for retries from voice-gateway

---

## Configuration

Provided via environment variables (see `src/config/env.ts`):
- Core: `PUBLIC_HOST`, `PUBLIC_PROTOCOL`, `BACKEND_PORT` (derives backend_url)
- DB: `DB_CONNECTION_STRING` (or default postgres://localhost:5432/postgres), `DB_SSL`, `DB_POOL_MAX`, `DB_READ_ONLY`
- Auth: `BACKEND_API_KEY` / `API_KEY` (for tool auth)

No secrets are committed to source control.

---

## Scaling Characteristics

- Scales by tool-call throughput
- Can be scaled independently of voice-gateway
- Safe to add background workers later (notifications, analytics)

---

## Why Postgres?

- Strong ACID guarantees
- Excellent concurrency control
- Flexible querying for analytics
- Natural fit for audit + event models

Redis or other caches may be added later for performance, but correctness always lives here.

---

## Operational Philosophy

This service is intentionally conservative:
- Correctness over cleverness
- Explicit transactions
- Clear audit trails
- Debuggable failures
