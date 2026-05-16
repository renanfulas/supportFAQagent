# Runbook - Contrato de Retrieval pgvector

Este runbook descreve a query de contrato do retrieval vetorial para o `supportFAQagent`. Ele serve como referencia para revisao tecnica, implementacao do backend e alinhamento entre schema SQL e adapter Python.

## Objetivo

Definir a forma minima da consulta que o backend precisa executar para recuperar chunks vetoriais do dominio correto, com score rastreavel e shape compativel com `RetrievedChunk`.

## Entradas logicas

- `domain_id`: dominio resolvido pelo backend.
- `query_embedding`: embedding da pergunta atual.
- `top_k`: quantidade maxima de chunks retornados.

## Saida obrigatoria

- `source`
- `title`
- `text`
- `score`

Esse shape deve continuar compativel com o contrato interno usado pelo adapter `PgVectorStore` e com o shape publico de `references` no `/chat`.

## Invariantes

- Sempre filtrar por `domain_id`.
- Nunca buscar em todos os dominios por padrao.
- Ignorar chunks com `embedding IS NULL`.
- Considerar apenas artigos com `status = 'active'`.
- Retornar `source`, `title`, `text` e `score` de forma rastreavel.
- Nao expor SQL, stack trace ou detalhes de persistencia para `ChatFlowService`.

## Query de contrato

Os placeholders abaixo sao conceituais. Este arquivo documenta o contrato; a execucao operacional fica em `tests/db/validate_pgvector_search.sql`.

```sql
SELECT
  a.source AS source,
  a.title AS title,
  c.chunk_text AS text,
  1 - (c.embedding <=> :query_embedding) AS score
FROM article_chunks c
JOIN articles a ON a.id = c.article_id
WHERE c.domain_id = :domain_id
  AND c.embedding IS NOT NULL
  AND a.status = 'active'
ORDER BY c.embedding <=> :query_embedding
LIMIT :top_k;
```

## Uso esperado por arquivo

- `migrations/001_initial_schema.sql`: cria schema base.
- `tests/db/test_01_extensions.sql` a `tests/db/test_05_isolation.sql`: contrato minimo de extensao, schema, idempotencia, busca vetorial e isolamento.
- `tests/db/validate_pgvector_search.sql`: validacao operacional da query vetorial em `psql`.
- este runbook: referencia de integracao para backend e revisao tecnica.

## Fronteira de responsabilidade

- Alexandre: schema SQL, migrations, query vetorial, validacao PostgreSQL.
- Renan: adapter Python, contrato do backend, testes do app e integracao com `/chat`.
- Silotto: runtime oficial e `DATABASE_URL` do ambiente HostGator.
