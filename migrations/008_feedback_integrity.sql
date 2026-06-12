-- Migration 008 - Version session hashes and make feedback retries idempotent.

ALTER TABLE chat_audits
  ADD COLUMN session_hash_version TEXT;

UPDATE chat_audits
SET session_hash_version = 'legacy-unversioned'
WHERE session_hash IS NOT NULL;

CREATE FUNCTION set_legacy_session_hash_version()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.session_hash IS NULL THEN
    NEW.session_hash_version := NULL;
  ELSIF NEW.session_hash_version IS NULL THEN
    NEW.session_hash_version := 'legacy-unversioned';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER chat_audits_legacy_hash_version
BEFORE INSERT OR UPDATE OF session_hash, session_hash_version ON chat_audits
FOR EACH ROW
EXECUTE FUNCTION set_legacy_session_hash_version();

ALTER TABLE chat_audits
  ADD CONSTRAINT chat_audits_session_hash_version_check
  CHECK (
    (session_hash IS NULL AND session_hash_version IS NULL)
    OR (session_hash IS NOT NULL AND session_hash_version IS NOT NULL)
  );

CREATE INDEX idx_chat_audits_feedback_context
ON chat_audits(request_id, session_hash, session_hash_version);

ALTER TABLE feedback
  ADD COLUMN message_id TEXT,
  ADD COLUMN session_hash_version TEXT,
  ADD COLUMN idempotency_key TEXT,
  ADD COLUMN feedback_fingerprint TEXT;

UPDATE feedback
SET session_hash_version = 'legacy-unversioned'
WHERE session_hash IS NOT NULL;

CREATE TRIGGER feedback_legacy_hash_version
BEFORE INSERT OR UPDATE OF session_hash, session_hash_version ON feedback
FOR EACH ROW
EXECUTE FUNCTION set_legacy_session_hash_version();

ALTER TABLE feedback
  ADD CONSTRAINT feedback_session_hash_version_check
  CHECK (
    (session_hash IS NULL AND session_hash_version IS NULL)
    OR (session_hash IS NOT NULL AND session_hash_version IS NOT NULL)
  ),
  ADD CONSTRAINT feedback_idempotency_fingerprint_check
  CHECK (idempotency_key IS NULL OR feedback_fingerprint IS NOT NULL);

CREATE UNIQUE INDEX idx_feedback_idempotency_key
ON feedback(idempotency_key)
WHERE idempotency_key IS NOT NULL;

CREATE INDEX idx_feedback_message_id
ON feedback(message_id)
WHERE message_id IS NOT NULL;
