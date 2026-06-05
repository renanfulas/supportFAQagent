-- Migration 002 - Web Auth (OTP WhatsApp V1B)
-- Autor: Alexandre Madeira
-- Data: 2026-06-04
--
-- Cria as tabelas de identidade de canal, sessoes web e desafios OTP.
-- Estas tabelas suportam o fluxo de verificacao de WhatsApp via OTP
-- descrito em docs/quality-plans/web-chat-v1b-postgres-n8n-plan.md
--
-- Regras de privacidade obrigatorias:
--   - phone_e164 nunca persiste nessas tabelas
--   - OTP puro nunca persiste — apenas code_digest (HMAC)
--   - phone_hash e derivado com IDENTITY_HASH_SECRET fora do banco
--
-- Nao editar 001_initial_schema.sql. Esta migration e independente.


-- Identidades de canal verificadas por OTP.
-- Uma identidade representa um numero de WhatsApp confirmado
-- associado a um canal. Sobrevive a restarts e multiplas sessoes.
CREATE TABLE verified_identities (
  id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  channel           TEXT        NOT NULL,
  phone_hash        TEXT        NOT NULL,
  phone_last4       TEXT        NOT NULL,
  verified_at       TIMESTAMPTZ NOT NULL,
  status            TEXT        NOT NULL DEFAULT 'verified',
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (channel, phone_hash),
  CHECK (status IN ('verified', 'revoked'))
);


-- Sessoes web anonimas e seu vinculo com identidade verificada.
-- Uma sessao nasce anonima (verified_identity_id NULL) e pode ser
-- promovida apos OTP confirmado. O hash do cookie nunca revela
-- o valor bruto da sessao.
CREATE TABLE web_sessions (
  id                       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  anonymous_session_hash   TEXT        NOT NULL UNIQUE,
  verified_identity_id     UUID        REFERENCES verified_identities(id) ON DELETE SET NULL,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- Desafios OTP ativos, consumidos e expirados.
-- O id e gerado pelo backend antes de persistir para garantir
-- rastreabilidade desde o momento de criacao.
-- code_digest armazena apenas o HMAC do OTP, nunca o codigo puro.
CREATE TABLE otp_challenges (
  id                       UUID        PRIMARY KEY,
  identity_candidate_hash  TEXT        NOT NULL,
  phone_last4              TEXT        NOT NULL,
  code_digest              TEXT        NOT NULL,
  expires_at               TIMESTAMPTZ NOT NULL,
  attempts_remaining       INT         NOT NULL,
  status                   TEXT        NOT NULL,
  created_at               TIMESTAMPTZ NOT NULL,
  consumed_at              TIMESTAMPTZ,
  delivery_id              UUID,
  delivery_status          TEXT,
  CHECK (attempts_remaining >= 0),
  CHECK (status IN ('pending', 'consumed', 'expired', 'delivery_failed'))
);


-- Indices

-- Lookup de identidade por canal e hash (cobre cooldown e verificacao de sessao)
-- Ja coberto pelo UNIQUE (channel, phone_hash) acima.

-- Filtragem de identidades ativas por canal
CREATE INDEX idx_verified_identities_channel_status
  ON verified_identities(channel, status);

-- Lookup de sessao por identidade vinculada (revogacao em massa, logout)
CREATE INDEX idx_web_sessions_identity
  ON web_sessions(verified_identity_id);

-- Limpeza de sessoes inativas por data
CREATE INDEX idx_web_sessions_last_seen
  ON web_sessions(last_seen_at);

-- Cooldown e rate limit: ultimos desafios por candidato
CREATE INDEX idx_otp_challenges_candidate_created
  ON otp_challenges(identity_candidate_hash, created_at DESC);

-- Filtragem de desafios pendentes (verificacao de tentativas ativas)
CREATE INDEX idx_otp_challenges_status_expires
  ON otp_challenges(status, expires_at);

-- Limpeza periodica de desafios expirados
CREATE INDEX idx_otp_challenges_expires_at
  ON otp_challenges(expires_at);


-- Limpeza periodica sugerida (executar via cron ou job separado):
--
--   DELETE FROM otp_challenges
--   WHERE expires_at < now() - INTERVAL '7 days';
--
--   DELETE FROM web_sessions
--   WHERE last_seen_at < now() - INTERVAL '90 days'
--     AND verified_identity_id IS NULL;
