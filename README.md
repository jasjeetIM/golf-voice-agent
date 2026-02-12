# Golf Voice Agent

Real-time voice reservation platform for golf tee times.

## System Architecture

The codebase is organized as two services plus shared contracts:
- `voice_gateway`: The realtime edge that handles Twilio media streams, OpenAI realtime
  agent orchestration, and backend tool bridging.
- `backend`: The domain service that exposes tool routes (`/v1/tools/...`) for inventory,
  reservations, and persistence.
- `shared`: Common Pydantic schemas and enums used by both services to keep request/response
  contracts consistent.

Runtime request/data flow:
1. Twilio PSTN/media stream traffic enters `voice_gateway`.
2. `voice_gateway` invokes backend tool endpoints when business logic or data is needed.
3. `backend` executes domain logic and reads/writes PostgreSQL tables.

## Repository Layout

Current top-level structure:

```text
backend/                 FastAPI backend app, domain services, migrations, seed script
voice_gateway/           FastAPI voice edge service (Twilio + realtime agent integration)
shared/                  Shared schemas/enums used across services
tests/unit/              Unit tests for backend services and voice_gateway modules
pyproject.toml           Dependencies and tool configuration (ruff/pytest/build)
.env                     Local defaults used by config modules
README.md                Project overview and local workflow
```

## Local Prerequisites

- Python 3.11+
- PostgreSQL (for backend persistence and optional voice observability logging)
- Twilio/OpenAI credentials when running full end-to-end flows

## Commands (1-7)

Run commands from repo root:

```bash
cd /Users/dhalijs1/Documents/voice_agent/golf-voice-agent
```

1. Install dev dependencies
```bash
python -m pip install -e ".[dev]"
```

2. Run lint checks
```bash
ruff check .
```

3. Run format checks
```bash
ruff format --check .
```

4. Run compile/syntax checks
```bash
python -m compileall backend voice_gateway shared tests
```

5. Run unit tests
```bash
pytest tests/unit -q
```

6. Build package artifacts
```bash
python -m build
```

7. Run both services locally
```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8081 --reload
uvicorn voice_gateway.app.main:app --host 0.0.0.0 --port 8080 --reload
```

## Optional Local Data Setup

Apply schema and seed example tee times after PostgreSQL is running:

```bash
psql "$DB_CONNECTION_STRING" -f backend/migrations/0001_init.sql
python backend/scripts/seed_slots.py
```
