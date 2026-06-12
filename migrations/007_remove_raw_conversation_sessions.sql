-- Migration 007 - Contract phase for sanitized conversation persistence.
--
-- Existing environments must run the resumable backfill and explicitly mark
-- contract readiness after the new writer has been deployed. Locks close the
-- race between the final readiness check and dropping the legacy column.

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';

LOCK TABLE conversations IN ACCESS EXCLUSIVE MODE;
LOCK TABLE messages IN ACCESS EXCLUSIVE MODE;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM conversations
    WHERE session_id IS NOT NULL
       OR session_hash IS NULL
       OR session_hash_version IS NULL
  ) THEN
    RAISE EXCEPTION
      'conversation privacy backfill is required before migration 007';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM messages
    WHERE redaction_version = 'legacy-unverified'
  ) THEN
    RAISE EXCEPTION
      'message privacy backfill is required before migration 007';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM conversation_privacy_rollout
    WHERE singleton = true
      AND phase = 'contract_ready'
      AND hash_secret_fingerprint IS NOT NULL
      AND hash_version IS NOT NULL
      AND backfill_completed_at IS NOT NULL
      AND contract_ready_at IS NOT NULL
      AND (
        last_legacy_write_at IS NULL
        OR last_legacy_write_at <= contract_ready_at
      )
  ) THEN
    RAISE EXCEPTION
      'explicit conversation contract readiness is required before migration 007';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM conversations AS conversation
    CROSS JOIN conversation_privacy_rollout AS rollout
    WHERE rollout.singleton = true
      AND conversation.session_hash_version <> rollout.hash_version
  ) THEN
    RAISE EXCEPTION
      'conversation hash version differs from the pinned backfill version';
  END IF;
END
$$;

DROP TRIGGER conversations_legacy_writer_guard ON conversations;
DROP FUNCTION mark_conversation_legacy_writer();

DROP INDEX IF EXISTS idx_conversations_session_domain;

ALTER TABLE conversations
  DROP CONSTRAINT conversations_session_identity_check,
  DROP COLUMN session_id;

ALTER TABLE conversations
  DROP COLUMN legacy_session_seen_at,
  ALTER COLUMN session_hash SET NOT NULL,
  ALTER COLUMN session_hash_version SET NOT NULL;

ALTER TABLE messages
  ALTER COLUMN redaction_version DROP DEFAULT;

UPDATE conversation_privacy_rollout
SET phase = 'contracted',
    contracted_at = clock_timestamp(),
    updated_at = clock_timestamp()
WHERE singleton = true;
