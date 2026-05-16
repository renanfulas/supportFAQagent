-- Migration 001 - Initial Schema
-- Autor: Alexandre Madeira
-- Data: 2026-05-11

-- Extensoes
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Dominios
CREATE TABLE domains (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  owner TEXT NOT NULL DEFAULT 'community',
  status TEXT NOT NULL DEFAULT 'active',
  config_version INT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Artigos versionados por dominio. O core deve continuar generico para
-- suporte, vendas, onboarding e outros setores.
CREATE TABLE articles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain_id UUID NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  source TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'markdown',
  external_id TEXT,
  content_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (domain_id, source)
);

-- Chunks com vetor
CREATE TABLE article_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  article_id UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  domain_id UUID NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
  chunk_index INT NOT NULL,
  chunk_text TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  token_estimate INT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  embedding VECTOR(1536),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (article_id, chunk_index)
);

-- Conversas
CREATE TABLE conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain_id UUID NOT NULL REFERENCES domains(id),
  channel TEXT NOT NULL DEFAULT 'api',
  session_id TEXT NOT NULL,
  external_conversation_id TEXT,
  status TEXT NOT NULL DEFAULT 'bot',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Mensagens
-- Nota: campo 'references' renomeado para 'message_references'
-- pois 'references' e palavra reservada no PostgreSQL
CREATE TABLE messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  provider TEXT,
  confidence DOUBLE PRECISION,
  escalated BOOLEAN NOT NULL DEFAULT false,
  error_code TEXT,
  latency_ms INT,
  message_references JSONB NOT NULL DEFAULT '[]'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indices
CREATE INDEX idx_articles_domain_status ON articles(domain_id, status);
CREATE INDEX idx_articles_domain_source_type_external ON articles(domain_id, source_type, external_id);
CREATE INDEX idx_chunks_domain_article ON article_chunks(domain_id, article_id);
CREATE INDEX idx_chunks_metadata_gin ON article_chunks USING gin(metadata);
CREATE INDEX idx_conversations_session_domain ON conversations(session_id, domain_id, updated_at DESC);
CREATE INDEX idx_conversations_domain_channel_external ON conversations(domain_id, channel, external_conversation_id);
CREATE INDEX idx_messages_conversation_created ON messages(conversation_id, created_at);

-- Indice vetorial (criar apos volume inicial de dados)
-- CREATE INDEX idx_chunks_embedding_cosine
-- ON article_chunks USING ivfflat (embedding vector_cosine_ops)
-- WITH (lists = 100);
