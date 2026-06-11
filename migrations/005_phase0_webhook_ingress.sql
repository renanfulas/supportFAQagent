-- Migration 005 - Persistent idempotency receipts for trusted webhook ingress.

CREATE TABLE webhook_ingress_receipts (
  idempotency_key_hash TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  request_id TEXT,
  payload_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'processing',
  attempt_count INT NOT NULL DEFAULT 1,
  last_error_code TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  delivered_at TIMESTAMPTZ,
  CHECK (status IN ('processing', 'delivered', 'retryable_failed')),
  CHECK (attempt_count >= 1)
);

CREATE INDEX idx_webhook_ingress_status_updated
ON webhook_ingress_receipts(status, updated_at);
