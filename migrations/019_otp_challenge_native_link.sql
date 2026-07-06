-- Migration 019 - Fase 3 (opcional) da ponte WhatsApp<->console: unificacao
-- de identidade via OTP web (Opcao B, opt-in -- decisao registrada em
-- docs/quality-plans/whatsapp-support-bridge-tech-plan.md).
--
-- O telefone bruto nunca sobrevive entre POST /web/auth/whatsapp/start e
-- /confirm (por desenho de privacidade -- so o phone_hash do dominio web
-- passa adiante). Para vincular retroativamente o historico do WhatsApp
-- nativo (que usa um dominio de hash diferente, PERSISTENCE_HASH_SECRET) sem
-- jamais persistir o telefone bruto, o hash nativo esperado e calculado UMA
-- VEZ em start() -- momento em que o telefone bruto ainda existe em memoria
-- -- e carregado nestas colunas efemeras ate confirm() consumir o desafio.
--
-- Sao HASHES (nao o telefone), no mesmo nivel de sensibilidade de
-- identity_candidate_hash ja existente nesta tabela; a linha inteira e
-- efemera (consumida/expirada).

ALTER TABLE otp_challenges
  ADD COLUMN native_session_hash_hermes TEXT,
  ADD COLUMN native_session_hash_meta TEXT;
