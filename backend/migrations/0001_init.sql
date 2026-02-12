-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1) customers
CREATE TABLE IF NOT EXISTS customers (
  customer_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  phone_e164 TEXT UNIQUE,
  email TEXT UNIQUE,
  full_name TEXT,
  preferences_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2) courses
CREATE TABLE IF NOT EXISTS courses (
  course_id TEXT PRIMARY KEY,
  course_name TEXT NOT NULL,
  timezone TEXT NOT NULL,
  phone_e164 TEXT,
  address_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3) tee_time_slots
CREATE TABLE IF NOT EXISTS tee_time_slots (
  slot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  course_id TEXT NOT NULL REFERENCES courses(course_id),
  start_ts TIMESTAMPTZ NOT NULL,
  capacity_players INT NOT NULL,
  players_booked INT NOT NULL DEFAULT 0,
  is_closed BOOLEAN NOT NULL DEFAULT FALSE,
  base_price_cents INT,
  currency TEXT NOT NULL DEFAULT 'USD',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT tee_time_slots_unique UNIQUE(course_id, start_ts)
);

CREATE TYPE tool_status AS ENUM ('PENDING','RUNNING','SUCCEEDED','FAILED');
CREATE TYPE tool_name AS ENUM (
  'search_tee_times',
  'book_tee_time',
  'modify_reservation',
  'cancel_reservation',
  'send_sms_confirmation',
  'get_reservation_details',
  'quote_reservation_change',
  'check_slot_capacity'
);
CREATE TYPE call_reservation_relationship AS ENUM ('CREATE','UPDATE_TIME','UPDATE_PLAYERS','CANCEL');
CREATE TYPE reservation_status AS ENUM ('BOOKED', 'CANCELLED');
CREATE TYPE reservation_type AS ENUM ('WALKING', 'RIDING');

CREATE TABLE IF NOT EXISTS reservations (
  reservation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  confirmation_code TEXT NOT NULL UNIQUE,
  slot_id UUID NOT NULL REFERENCES tee_time_slots(slot_id),
  customer_id UUID NOT NULL REFERENCES customers(customer_id),
  num_holes SMALLINT NOT NULL CHECK (num_holes IN (9, 18)),
  reservation_type reservation_type NOT NULL,
  num_players INT NOT NULL,
  status reservation_status NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by_call_id TEXT,
  updated_by_call_id TEXT,
  version INT NOT NULL DEFAULT 1
);

-- 5) reservation_changes
CREATE TYPE reservation_change_type AS ENUM ('CREATE', 'UPDATE_TIME', 'UPDATE_PLAYERS', 'CANCEL', 'UPDATE_ROUND_TYPE');

CREATE TABLE IF NOT EXISTS reservation_changes (
  change_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  reservation_id UUID NOT NULL REFERENCES reservations(reservation_id),
  change_type reservation_change_type NOT NULL,
  changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  call_id TEXT,
  tool_call_id UUID,
  idempotency_key TEXT UNIQUE,
  before_json JSONB,
  after_json JSONB,
  reason_code TEXT
);

-- 6) calls
CREATE TYPE call_outcome AS ENUM ('NO_ACTION','BOOKED','MODIFIED','CANCELLED','FAILED','HANDOFF');
CREATE TYPE confirmation_status AS ENUM ('NOT_NEEDED','PENDING','SENT','FAILED');

CREATE TABLE IF NOT EXISTS calls (
  call_id TEXT PRIMARY KEY,
  from_number TEXT NOT NULL,
  to_number TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL,
  ended_at TIMESTAMPTZ,
  final_outcome call_outcome NOT NULL,
  final_outcome_reason TEXT,
  confirmation_status confirmation_status NOT NULL DEFAULT 'NOT_NEEDED',
  model TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 7) call_events (raw Twilio + transport events)
CREATE TABLE IF NOT EXISTS call_events (
  event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  call_id TEXT NOT NULL REFERENCES calls(call_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  event_type TEXT NOT NULL,
  direction TEXT,
  source TEXT,
  payload_json JSONB
);

CREATE INDEX IF NOT EXISTS call_events_call_id_created_at_idx ON call_events(call_id, created_at);
CREATE INDEX IF NOT EXISTS call_events_event_type_idx ON call_events(event_type);
CREATE INDEX IF NOT EXISTS call_events_payload_gin ON call_events USING GIN (payload_json);

-- 8) session_events (RealtimeSession events)
CREATE TABLE IF NOT EXISTS session_events (
  event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  call_id TEXT NOT NULL REFERENCES calls(call_id),
  session_id TEXT,
  agent_name TEXT,
  event_type TEXT NOT NULL,
  direction TEXT,
  item_id TEXT,
  tool_call_id TEXT,
  payload_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS session_events_call_id_created_at_idx ON session_events(call_id, created_at);
CREATE INDEX IF NOT EXISTS session_events_event_type_idx ON session_events(event_type);
CREATE INDEX IF NOT EXISTS session_events_item_id_idx ON session_events(item_id);
CREATE INDEX IF NOT EXISTS session_events_payload_gin ON session_events USING GIN (payload_json);

-- 9) realtime_items (normalized item state)
CREATE TABLE IF NOT EXISTS realtime_items (
  item_id TEXT PRIMARY KEY,
  previous_item_id TEXT,
  call_id TEXT NOT NULL REFERENCES calls(call_id),
  session_id TEXT,
  role TEXT,
  type TEXT NOT NULL,
  status TEXT,
  content_json JSONB,
  tool_call_id TEXT,
  tool_name TEXT,
  created_from_event_id UUID REFERENCES session_events(event_id),
  last_event_id UUID REFERENCES session_events(event_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS realtime_items_call_id_idx ON realtime_items(call_id);
CREATE INDEX IF NOT EXISTS realtime_items_tool_call_id_idx ON realtime_items(tool_call_id);

-- 10) tool_calls (canonical tool usage log)
CREATE TABLE IF NOT EXISTS tool_calls (
  tool_call_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  call_id TEXT NOT NULL REFERENCES calls(call_id),
  session_id TEXT,
  turn_id INT NOT NULL DEFAULT 0,
  tool_name tool_name NOT NULL,
  args_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  result_json JSONB,
  status tool_status NOT NULL DEFAULT 'PENDING',
  error_message TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at TIMESTAMPTZ,
  latency_ms INT,
  reservation_id UUID REFERENCES reservations(reservation_id),
  change_id UUID REFERENCES reservation_changes(change_id),
  tool_call_external_id TEXT,
  tool_item_id TEXT,
  realtime_status TEXT,
  arguments_raw TEXT,
  output_raw TEXT,
  agent_name TEXT
);

CREATE INDEX IF NOT EXISTS tool_calls_call_id_idx ON tool_calls(call_id);
CREATE INDEX IF NOT EXISTS tool_calls_tool_call_external_id_idx ON tool_calls(tool_call_external_id);

-- 11) mcp_calls (subset of tool_calls)
CREATE TABLE IF NOT EXISTS mcp_calls (
  mcp_call_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tool_call_id UUID REFERENCES tool_calls(tool_call_id),
  tool_call_external_id TEXT,
  call_id TEXT REFERENCES calls(call_id),
  session_id TEXT,
  server_name TEXT,
  method TEXT,
  request_json JSONB,
  response_json JSONB,
  error_message TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at TIMESTAMPTZ,
  latency_ms INT
);

CREATE INDEX IF NOT EXISTS mcp_calls_tool_call_id_idx ON mcp_calls(tool_call_id);
CREATE INDEX IF NOT EXISTS mcp_calls_tool_call_external_id_idx ON mcp_calls(tool_call_external_id);

-- 12) call_reservations
CREATE TABLE IF NOT EXISTS call_reservations (
  call_reservation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  call_id TEXT NOT NULL REFERENCES calls(call_id),
  reservation_id UUID NOT NULL REFERENCES reservations(reservation_id),
  relationship call_reservation_relationship NOT NULL,
  is_primary BOOLEAN NOT NULL DEFAULT FALSE,
  change_id UUID REFERENCES reservation_changes(change_id),
  ts TIMESTAMPTZ NOT NULL DEFAULT now()
);
