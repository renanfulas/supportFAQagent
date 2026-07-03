-- Migration 014 - Staff do console de suporte (Fase A do plano tecnico).
--
-- Aditiva. Cria as tabelas de autenticacao staff da fachada /web/support/*:
-- staff nao e cliente, entao nada aqui toca customers/verified_identities.
--
-- Privacidade: somente phone_hash (HMAC com IDENTITY_HASH_SECRET, mesmo HMAC
-- de verified_identities) + phone_last4. O telefone bruto nunca e persistido;
-- no fluxo de lembrete de dispositivo ele viaja apenas no cookie HttpOnly do
-- proprio operador e e validado contra o phone_hash antes de qualquer entrega.
--
-- Sessao staff: token bruto so no cookie; aqui vive o HMAC do token com
-- expiracao fixa na proxima SUPPORT_STAFF_SESSION_EXPIRY_HOUR do fuso do time.

CREATE TABLE staff_members (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  phone_hash TEXT NOT NULL UNIQUE,
  phone_last4 TEXT NOT NULL,
  display_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT staff_members_status_check CHECK (status IN ('active', 'disabled'))
);

CREATE TABLE staff_sessions (
  session_hash TEXT PRIMARY KEY,
  staff_id UUID NOT NULL REFERENCES staff_members(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_staff_sessions_staff ON staff_sessions (staff_id);
CREATE INDEX idx_staff_sessions_expires ON staff_sessions (expires_at);

CREATE TABLE staff_login_hints (
  hint_hash TEXT PRIMARY KEY,
  staff_id UUID NOT NULL REFERENCES staff_members(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_used_at TIMESTAMPTZ
);

CREATE INDEX idx_staff_login_hints_staff ON staff_login_hints (staff_id);
