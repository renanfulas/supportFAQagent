-- Migration 012 - Warehouse de resumos de conversa (persistencia em camadas, Fase 3).
--
-- Base analitica/RAG alimentada pelo batch noturno idempotente
-- (scripts/summarize_conversations.py). NAO ha PII crua aqui: o texto e
-- sanitizado/redigido (REDACTION_VERSION) antes de ir ao modelo, e o cliente e
-- identificado por id/hash estavel (customer_ref), nunca telefone cru.
-- Idempotencia por conversa via UNIQUE (domain, conversation_key): re-rodar o
-- batch sobrescreve o mesmo registro.

CREATE TABLE conversation_summaries (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  domain            TEXT NOT NULL,
  customer_ref      TEXT NOT NULL,
  problem           TEXT NOT NULL,
  solution          TEXT NOT NULL,
  status            TEXT NOT NULL,
  source_turn_count INT NOT NULL,
  redaction_version TEXT NOT NULL,
  model             TEXT NOT NULL,
  summarized_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  conversation_key  TEXT NOT NULL,
  CONSTRAINT conversation_summaries_status_check
    CHECK (status IN ('resolvido', 'em_aberto', 'escalado')),
  CONSTRAINT conversation_summaries_unique_per_conversation
    UNIQUE (domain, conversation_key)
);

CREATE INDEX idx_conversation_summaries_lookup
  ON conversation_summaries (domain, customer_ref);
