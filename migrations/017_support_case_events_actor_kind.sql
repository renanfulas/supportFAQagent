-- Migration 017 - Ator generico em support_case_events.
--
-- Ate aqui, todo evento de suporte era gerado por staff (console). A ponte
-- WhatsApp<->console precisa registrar tambem mensagens do CLIENTE e acoes do
-- SISTEMA (ex.: purga de binding) na mesma trilha de auditoria por caso.
--
-- IMPORTANTE para quem consumir esta migration: app/support/repository.py
-- (SupportCaseRepository.get_case_events) faz hoje um INNER JOIN em
-- staff_members via actor_staff_id. Com actor_staff_id agora nullable, esse
-- INNER JOIN precisa virar LEFT JOIN (feito neste mesmo PR) -- senao eventos
-- de cliente/sistema desaparecem em silencio do historico do console.

ALTER TABLE support_case_events
  ALTER COLUMN actor_staff_id DROP NOT NULL;

ALTER TABLE support_case_events
  ADD COLUMN actor_kind TEXT NOT NULL DEFAULT 'staff',
  ADD COLUMN actor_customer_id UUID REFERENCES customers(id) ON DELETE SET NULL;

ALTER TABLE support_case_events
  ADD CONSTRAINT support_case_events_actor_kind_check
  CHECK (actor_kind IN ('staff', 'customer', 'system'));

-- Exatamente um ator preenchido conforme actor_kind: staff -> actor_staff_id;
-- customer -> actor_customer_id; system -> nenhum dos dois.
ALTER TABLE support_case_events
  ADD CONSTRAINT support_case_events_actor_shape_check
  CHECK (
    (actor_kind = 'staff' AND actor_staff_id IS NOT NULL AND actor_customer_id IS NULL)
    OR (actor_kind = 'customer' AND actor_customer_id IS NOT NULL AND actor_staff_id IS NULL)
    OR (actor_kind = 'system' AND actor_staff_id IS NULL AND actor_customer_id IS NULL)
  );

CREATE INDEX idx_support_case_events_actor_customer
  ON support_case_events (actor_customer_id)
  WHERE actor_customer_id IS NOT NULL;
