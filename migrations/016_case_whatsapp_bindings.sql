-- Migration 016 - Ponte WhatsApp<->console: binding cifrado do wa_id por caso.
--
-- Guarda o identificador WhatsApp (wa_id, E.164) do cliente CIFRADO
-- (app/support/wa_binding.py, chave SUPPORT_WA_ENC_KEY), escopado a um unico
-- support_case aberto. Retencao dupla (o que vier primeiro): purgado quando o
-- caso fecha/cancela, ou apos SUPPORT_WA_BINDING_MAX_DAYS (default 15 dias)
-- sem resolucao. O vinculo caso<->wa_id nasce do token HMAC do deep link
-- (app/support/wa_binding.py:mint_case_token/resolve_case_token), nao de
-- phone_hash -- casos nativos (WhatsApp) provavelmente nao tem customer_id.

CREATE TABLE case_whatsapp_bindings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id UUID NOT NULL REFERENCES support_cases(id) ON DELETE CASCADE,
  wa_id_encrypted BYTEA NOT NULL,
  -- HMAC deterministico do wa_id (sub-chave derivada de SUPPORT_WA_ENC_KEY,
  -- separacao por contexto -- ver app/support/wa_binding.py). Fernet e nao-
  -- deterministico (IV aleatorio), entao wa_id_encrypted nao e comparavel por
  -- igualdade; este hash existe so para achar o caso aberto de um wa_id em
  -- mensagens repetidas, sem decifrar/varrer todas as linhas.
  wa_id_hash TEXT NOT NULL,
  last_customer_message_at TIMESTAMPTZ,
  bound_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  unbound_at TIMESTAMPTZ,
  CONSTRAINT case_whatsapp_bindings_case_unique UNIQUE (case_id)
);

-- Lookup do binding vivo de um caso (webhook inbound, compositor do atendente).
CREATE INDEX idx_case_wa_bindings_open
  ON case_whatsapp_bindings (case_id)
  WHERE unbound_at IS NULL;

-- Mensagem repetida do mesmo wa_id (apos o primeiro bind): achar o caso aberto.
CREATE INDEX idx_case_wa_bindings_wa_id_hash
  ON case_whatsapp_bindings (wa_id_hash)
  WHERE unbound_at IS NULL;

-- Varredura do job de purga por teto de retencao (15 dias sem resolucao).
CREATE INDEX idx_case_wa_bindings_expiry
  ON case_whatsapp_bindings (expires_at)
  WHERE unbound_at IS NULL;
