# Golf Voice Agent (Prototype)

A prototype voice agent that answers a phone call (via Twilio Media Streams) and performs golf tee-time actions (search/book/modify/cancel) using a demo backend.

This repo is organized as a **pnpm monorepo** with two services:
- **voice-gateway**: Twilio webhook + WebSocket for Media Streams + (later) OpenAI realtime voice agent
- **demo-backend**: deterministic tee-time inventory + reservations API (for a reliable demo)

> Phase 0 goal: basic plumbing works end-to-end (gateway + backend + schemas), with WebSocket logging of Twilio stream events and HTTP endpoints for tee-time workflows.

---

## Architecture (high level)

**Caller → Twilio Voice → Twilio Media Streams (WS) → voice-gateway → (later) OpenAI Realtime Voice Agent → tools → demo-backend**

In Phase 0, we implement:
- `/twilio/inbound` returns TwiML `<Connect><Stream .../>` so Twilio can stream audio to us
- `/twilio/stream` accepts a WebSocket and logs Twilio `start/media/mark/stop` events
- `demo-backend` implements REST tool endpoints:
  - `search-tee-times`
  - `book-tee-time`
  - `modify-reservation`
  - `cancel-reservation`

---