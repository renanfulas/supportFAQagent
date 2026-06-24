-- Migration 009 - Customer identity and durable support cases.
--
-- Expand-only foundation for WhatsApp-authenticated customer history,
-- frontend preferences and human handoff tickets. This migration must not
-- change existing chat, Auth or outbox behavior by itself.

CREATE TABLE customers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  status TEXT NOT NULL DEFAULT 'active',
  display_label TEXT,
  default_channel TEXT,
  last_seen_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT customers_status_check
    CHECK (status IN ('active', 'merged', 'disabled'))
);

CREATE INDEX idx_customers_status
  ON customers(status, updated_at DESC);

CREATE INDEX idx_customers_last_seen
  ON customers(last_seen_at DESC)
  WHERE last_seen_at IS NOT NULL;

ALTER TABLE verified_identities
  ADD COLUMN customer_id UUID REFERENCES customers(id) ON DELETE SET NULL;

CREATE INDEX idx_verified_identities_customer
  ON verified_identities(customer_id)
  WHERE customer_id IS NOT NULL;

ALTER TABLE conversations
  ADD COLUMN customer_id UUID REFERENCES customers(id) ON DELETE SET NULL;

CREATE INDEX idx_conversations_customer
  ON conversations(customer_id, last_message_at DESC)
  WHERE customer_id IS NOT NULL;

CREATE TABLE customer_preferences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  domain_id UUID REFERENCES domains(id) ON DELETE CASCADE,
  preferences_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  version INT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT customer_preferences_version_check CHECK (version >= 1),
  CONSTRAINT customer_preferences_json_object_check
    CHECK (jsonb_typeof(preferences_json) = 'object')
);

CREATE UNIQUE INDEX idx_customer_preferences_customer_global
  ON customer_preferences(customer_id)
  WHERE domain_id IS NULL;

CREATE UNIQUE INDEX idx_customer_preferences_customer_domain
  ON customer_preferences(customer_id, domain_id)
  WHERE domain_id IS NOT NULL;

CREATE INDEX idx_customer_preferences_domain
  ON customer_preferences(domain_id)
  WHERE domain_id IS NOT NULL;

CREATE TABLE support_cases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain_id UUID NOT NULL REFERENCES domains(id),
  customer_id UUID REFERENCES customers(id) ON DELETE SET NULL,
  conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
  opening_message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
  request_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  priority TEXT NOT NULL DEFAULT 'normal',
  reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
  context_snapshot_sanitized JSONB NOT NULL DEFAULT '{}'::jsonb,
  idempotency_key TEXT NOT NULL,
  assigned_team TEXT,
  opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed_at TIMESTAMPTZ,
  CONSTRAINT support_cases_idempotency_key_unique UNIQUE (idempotency_key),
  CONSTRAINT support_cases_status_check
    CHECK (status IN ('open', 'in_progress', 'waiting_customer', 'closed', 'cancelled')),
  CONSTRAINT support_cases_priority_check
    CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
  CONSTRAINT support_cases_reason_codes_array_check
    CHECK (jsonb_typeof(reason_codes) = 'array'),
  CONSTRAINT support_cases_context_snapshot_object_check
    CHECK (jsonb_typeof(context_snapshot_sanitized) = 'object'),
  CONSTRAINT support_cases_closed_at_check
    CHECK (
      (status IN ('closed', 'cancelled') AND closed_at IS NOT NULL)
      OR (status NOT IN ('closed', 'cancelled') AND closed_at IS NULL)
    )
);

CREATE INDEX idx_support_cases_domain_status_opened
  ON support_cases(domain_id, status, opened_at DESC);

CREATE INDEX idx_support_cases_customer
  ON support_cases(customer_id, opened_at DESC)
  WHERE customer_id IS NOT NULL;

CREATE INDEX idx_support_cases_conversation
  ON support_cases(conversation_id)
  WHERE conversation_id IS NOT NULL;

CREATE INDEX idx_support_cases_request
  ON support_cases(request_id);
