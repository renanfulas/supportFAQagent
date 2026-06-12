-- Migration 006 - Expand phase for safe conversation history.
--
-- Old writers may continue inserting session_id while new writers insert only
-- session_hash/session_hash_version. The legacy-write trigger invalidates the
-- contract-ready marker whenever an old writer is observed.

ALTER TABLE conversations
  ADD COLUMN session_hash TEXT,
  ADD COLUMN session_hash_version TEXT,
  ADD COLUMN last_message_at TIMESTAMPTZ,
  ADD COLUMN legacy_session_seen_at TIMESTAMPTZ;

ALTER TABLE conversations
  ALTER COLUMN session_id DROP NOT NULL;

ALTER TABLE conversations
  ADD CONSTRAINT conversations_session_identity_check
  CHECK (
    session_id IS NOT NULL
    OR (session_hash IS NOT NULL AND session_hash_version IS NOT NULL)
  ) NOT VALID;

ALTER TABLE conversations
  VALIDATE CONSTRAINT conversations_session_identity_check;

ALTER TABLE messages
  ADD COLUMN turn_id UUID,
  ADD COLUMN message_sequence BIGINT GENERATED ALWAYS AS IDENTITY,
  ADD COLUMN request_id TEXT,
  ADD COLUMN channel TEXT NOT NULL DEFAULT 'api',
  ADD COLUMN handoff_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN redaction_version TEXT NOT NULL DEFAULT 'legacy-unverified',
  ADD COLUMN chat_audit_id UUID REFERENCES chat_audits(id) ON DELETE SET NULL;

ALTER TABLE chat_audits
  ADD COLUMN turn_id UUID NOT NULL DEFAULT gen_random_uuid(),
  ADD COLUMN channel TEXT NOT NULL DEFAULT 'api',
  ADD COLUMN request_fingerprint TEXT;

ALTER TABLE chat_audits
  DROP CONSTRAINT IF EXISTS chat_audits_request_id_key;

CREATE TABLE conversation_privacy_rollout (
  singleton BOOLEAN PRIMARY KEY DEFAULT true CHECK (singleton),
  phase TEXT NOT NULL DEFAULT 'expanded'
    CHECK (phase IN ('expanded', 'backfilled', 'contract_ready', 'contracted')),
  hash_secret_fingerprint TEXT,
  hash_version TEXT,
  last_legacy_write_at TIMESTAMPTZ,
  backfill_completed_at TIMESTAMPTZ,
  contract_ready_at TIMESTAMPTZ,
  contracted_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

INSERT INTO conversation_privacy_rollout (
  singleton,
  phase,
  last_legacy_write_at
)
SELECT
  true,
  'expanded',
  CASE
    WHEN EXISTS (SELECT 1 FROM conversations WHERE session_id IS NOT NULL)
      THEN clock_timestamp()
  END;

CREATE FUNCTION mark_conversation_legacy_writer()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.session_id IS NOT NULL THEN
    NEW.legacy_session_seen_at := clock_timestamp();
    UPDATE conversation_privacy_rollout
    SET phase = 'expanded',
        last_legacy_write_at = clock_timestamp(),
        backfill_completed_at = NULL,
        contract_ready_at = NULL,
        updated_at = clock_timestamp()
    WHERE singleton = true;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER conversations_legacy_writer_guard
BEFORE INSERT OR UPDATE OF session_id ON conversations
FOR EACH ROW
EXECUTE FUNCTION mark_conversation_legacy_writer();

CREATE UNIQUE INDEX idx_chat_audits_request_fingerprint
ON chat_audits(request_id, request_fingerprint)
WHERE request_fingerprint IS NOT NULL;

CREATE UNIQUE INDEX idx_messages_turn_role
ON messages(conversation_id, turn_id, role)
WHERE turn_id IS NOT NULL;

CREATE INDEX idx_messages_request ON messages(request_id);
CREATE INDEX idx_messages_retention ON messages(created_at);
CREATE INDEX idx_messages_conversation_sequence
ON messages(conversation_id, message_sequence DESC);
CREATE INDEX idx_conversations_last_message ON conversations(last_message_at);
CREATE INDEX idx_chat_audits_request ON chat_audits(request_id, created_at DESC);

-- Required by the new writer during the expand window. Legacy rows have a
-- NULL session_hash until the resumable backfill processes them.
CREATE UNIQUE INDEX idx_conversations_active_session
ON conversations(domain_id, channel, session_hash)
WHERE session_hash IS NOT NULL
  AND status IN ('bot', 'handoff_pending', 'human_active');
