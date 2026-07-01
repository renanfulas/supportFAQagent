-- Migration 013 - Contato do cliente e gate de consentimento LGPD (Sprint 4b).
--
-- Forward-only. Suporta o fluxo do web chat: apos OTP confirmado, o cliente
-- informa nome/e-mail (guardados em customers para reaproveitar em tickets
-- futuros do mesmo cliente). O support_case nasce imediatamente na transacao
-- do turno escalado (como hoje), mas com status intermediario
-- 'pending_consent' quando o gate esta ativo; a notificacao ao time so e
-- enfileirada depois que o cliente confirma via POST /web/handoff/consent.
--
-- Privacidade: diferente do telefone (so phone_hash/phone_last4), o e-mail
-- fica legivel porque a equipe precisa dele para contato real; validado no
-- backend antes de gravar, nunca aparece em log operacional.
--
-- Nao ha coluna de "lembrete enviado": o lembrete de OTP nao completado e
-- client-side (o widget reusa POST /web/auth/whatsapp/start), porque o
-- telefone bruto nunca fica persistido em otp_challenges (so o hash) -- nao
-- existe onde um job assincrono descobriria para quem reenviar.

ALTER TABLE customers ADD COLUMN email TEXT NULL;

ALTER TABLE support_cases DROP CONSTRAINT support_cases_status_check;
ALTER TABLE support_cases ADD CONSTRAINT support_cases_status_check
  CHECK (status IN ('pending_consent', 'open', 'in_progress', 'waiting_customer', 'closed', 'cancelled'));
