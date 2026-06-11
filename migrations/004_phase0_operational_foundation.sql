-- Migration 004 - Operational audit, reliable feedback and transactional outbox.

CREATE TABLE chat_audits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id TEXT NOT NULL UNIQUE,
  domain_id UUID NOT NULL REFERENCES domains(id),
  session_hash TEXT,
  question_sanitized TEXT NOT NULL,
  answer_sanitized TEXT NOT NULL,
  confidence DOUBLE PRECISION NOT NULL,
  escalated BOOLEAN NOT NULL DEFAULT false,
  handoff_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
  message_references JSONB NOT NULL DEFAULT '[]'::jsonb,
  error_code TEXT,
  redaction_version TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE feedback (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id TEXT,
  chat_audit_id UUID REFERENCES chat_audits(id) ON DELETE SET NULL,
  session_hash TEXT,
  helpful BOOLEAN NOT NULL,
  reason TEXT,
  comment_sanitized TEXT,
  source TEXT NOT NULL,
  context_status TEXT NOT NULL,
  context_mismatch BOOLEAN NOT NULL DEFAULT false,
  redaction_version TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (context_status IN ('matched', 'orphan'))
);

CREATE TABLE operational_outbox (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  request_id TEXT,
  payload_sanitized JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempt_count INT NOT NULL DEFAULT 0,
  available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  locked_at TIMESTAMPTZ,
  last_error_code TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at TIMESTAMPTZ,
  CHECK (status IN ('pending', 'processing', 'delivered', 'retryable_failed', 'dead_letter')),
  CHECK (attempt_count >= 0)
);

CREATE INDEX idx_chat_audits_created ON chat_audits(created_at);
CREATE INDEX idx_feedback_request ON feedback(request_id);
CREATE INDEX idx_feedback_created ON feedback(created_at);
CREATE INDEX idx_outbox_dispatch ON operational_outbox(status, available_at, created_at);
