-- Migration 011 - Durable sticky domain binding store.
--
-- Forward-only. Durable backing for SessionDomainStore
-- (whatsapp-sticky-domain-routing-plan). Remembers which domain a conversational
-- session chose (for example `vendas`) so generic follow-ups stay in that domain
-- across process restarts and across workers/replicas, instead of the
-- InMemorySessionDomainStore that dies per-process. Reads/writes are a single row
-- by primary key and are fail-open: a database hiccup degrades stickiness to
-- "show the menu", never breaks the channel.
--
-- Privacy: session_id_hash is the ALREADY-sanitized channel session id (a digest
-- such as whatsapp:hermes:<digest> / whatsapp:meta:<digest>) - NEVER a raw wa_id,
-- phone number, or message text. Only a domain name and timestamps live here.
--
-- TTL: get() filters by `expires_at > now()`; NULL means never expires. set()
-- refreshes expires_at on every write (upsert).

CREATE TABLE session_domain_binding (
  session_id_hash TEXT PRIMARY KEY,
  domain          TEXT NOT NULL,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at      TIMESTAMPTZ
);

-- Housekeeping sweep of expired bindings (get() already filters, this only keeps
-- the table small): DELETE FROM session_domain_binding WHERE expires_at < now().
CREATE INDEX idx_session_domain_binding_expires_at
  ON session_domain_binding(expires_at);
