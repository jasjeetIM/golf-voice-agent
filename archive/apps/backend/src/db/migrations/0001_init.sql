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
CREATE TYPE tool_name AS ENUM ('search_tee_times','book_tee_time','modify_reservation','cancel_reservation','send_sms_confirmation');
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
  idempotency_key TEXT NOT NULL UNIQUE,
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
  model TEXT
);

-- 7) call_events
CREATE TABLE IF NOT EXISTS call_events (
  event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  call_id TEXT NOT NULL REFERENCES calls(call_id),
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  event_type TEXT NOT NULL,
  payload_json JSONB
);

-- 8) agent_messages
CREATE TABLE IF NOT EXISTS agent_messages (
  message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  call_id TEXT NOT NULL REFERENCES calls(call_id),
  turn_id INT NOT NULL,
  text TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 9) tool_calls
CREATE TABLE IF NOT EXISTS tool_calls (
  tool_call_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  call_id TEXT NOT NULL REFERENCES calls(call_id),
  turn_id INT NOT NULL,
  tool_name tool_name NOT NULL,
  args_json JSONB NOT NULL,
  result_json JSONB,
  status tool_status NOT NULL,
  error_message TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at TIMESTAMPTZ,
  latency_ms INT,
  reservation_id UUID REFERENCES reservations(reservation_id),
  change_id UUID REFERENCES reservation_changes(change_id)
);

-- 10) call_reservations
CREATE TABLE IF NOT EXISTS call_reservations (
  call_reservation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  call_id TEXT NOT NULL REFERENCES calls(call_id),
  reservation_id UUID NOT NULL REFERENCES reservations(reservation_id),
  relationship call_reservation_relationship NOT NULL,
  is_primary BOOLEAN NOT NULL DEFAULT FALSE,
  change_id UUID REFERENCES reservation_changes(change_id),
  ts TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 11) notifications_outbox
CREATE TYPE notification_status AS ENUM ('PENDING','SENT','FAILED');
CREATE TYPE notification_channel AS ENUM ('SMS','EMAIL');

CREATE TABLE IF NOT EXISTS notifications_outbox (
  notification_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  call_id TEXT REFERENCES calls(call_id),
  reservation_id UUID REFERENCES reservations(reservation_id),
  channel notification_channel NOT NULL,
  to_address TEXT NOT NULL,
  template_id TEXT NOT NULL,
  payload_json JSONB NOT NULL,
  status notification_status NOT NULL DEFAULT 'PENDING',
  attempt_count INT NOT NULL DEFAULT 0,
  next_retry_at TIMESTAMPTZ,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  sent_at TIMESTAMPTZ
);
