-- Migration 015 - Dono do caso e historico auditavel (Fase B do console).
--
-- Aditiva. `assigned_team` (coluna de equipe da 009) fica intocada; o dono
-- individual vive em `assignee_staff_id`, o historico de transicoes em
-- `support_case_events`. Nenhuma linha existente muda: coluna nullable +
-- tabela nova, sem rewrite, sem downtime esperado.

ALTER TABLE support_cases
  ADD COLUMN assignee_staff_id UUID REFERENCES staff_members(id);

CREATE INDEX idx_support_cases_assignee ON support_cases (assignee_staff_id)
  WHERE assignee_staff_id IS NOT NULL;

CREATE TABLE support_case_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id UUID NOT NULL REFERENCES support_cases(id),
  actor_staff_id UUID NOT NULL REFERENCES staff_members(id),
  action TEXT NOT NULL,
  from_status TEXT NOT NULL,
  to_status TEXT NOT NULL,
  note_sanitized TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_support_case_events_case
  ON support_case_events (case_id, created_at);
