-- Validate pgvector retrieval contract with executable fixtures.
-- Use this file after applying migrations/001_initial_schema.sql.
-- It validates the operational SQL shape that backs the pgvector adapter.
--
-- Related files:
-- - migrations/001_initial_schema.sql: schema base
-- - tests/db/test_01_extensions.sql .. test_05_isolation.sql: contrato minimo
-- - docs/runbooks/pgvector-retrieval-contract.md: query de contrato

BEGIN;

INSERT INTO domains (id, name, display_name) VALUES
  ('00000000-0000-0000-0000-000000000101', 'domain-a', 'Domain A'),
  ('00000000-0000-0000-0000-000000000102', 'domain-b', 'Domain B')
ON CONFLICT (name) DO NOTHING;

INSERT INTO articles (id, domain_id, title, source, content_hash, status) VALUES
  (
    '00000000-0000-0000-0000-000000000201',
    '00000000-0000-0000-0000-000000000101',
    'Article Active A',
    'knowledge/a-active.md',
    md5('article active a'),
    'active'
  ),
  (
    '00000000-0000-0000-0000-000000000202',
    '00000000-0000-0000-0000-000000000101',
    'Article Inactive A',
    'knowledge/a-inactive.md',
    md5('article inactive a'),
    'inactive'
  ),
  (
    '00000000-0000-0000-0000-000000000203',
    '00000000-0000-0000-0000-000000000102',
    'Article Active B',
    'knowledge/b-active.md',
    md5('article active b'),
    'active'
  )
ON CONFLICT (domain_id, source) DO NOTHING;

INSERT INTO article_chunks (
  id,
  article_id,
  domain_id,
  chunk_index,
  chunk_text,
  content_hash,
  token_estimate,
  metadata,
  embedding
) VALUES
  (
    '00000000-0000-0000-0000-000000000301',
    '00000000-0000-0000-0000-000000000201',
    '00000000-0000-0000-0000-000000000101',
    0,
    'chunk active domain a',
    md5('chunk active domain a'),
    5,
    '{"title":"Article Active A"}'::jsonb,
    array_fill(0.1, ARRAY[1536])::vector
  ),
  (
    '00000000-0000-0000-0000-000000000302',
    '00000000-0000-0000-0000-000000000202',
    '00000000-0000-0000-0000-000000000101',
    0,
    'chunk inactive article domain a',
    md5('chunk inactive article domain a'),
    6,
    '{"title":"Article Inactive A"}'::jsonb,
    array_fill(0.1, ARRAY[1536])::vector
  ),
  (
    '00000000-0000-0000-0000-000000000303',
    '00000000-0000-0000-0000-000000000203',
    '00000000-0000-0000-0000-000000000102',
    0,
    'chunk active domain b',
    md5('chunk active domain b'),
    5,
    '{"title":"Article Active B"}'::jsonb,
    array_fill(0.1, ARRAY[1536])::vector
  ),
  (
    '00000000-0000-0000-0000-000000000304',
    '00000000-0000-0000-0000-000000000201',
    '00000000-0000-0000-0000-000000000101',
    1,
    'chunk without embedding domain a',
    md5('chunk without embedding domain a'),
    7,
    '{"title":"Article Active A"}'::jsonb,
    NULL
  )
ON CONFLICT (article_id, chunk_index) DO NOTHING;

-- Expected result:
-- - returns only chunks from domain A
-- - excludes domain B
-- - excludes inactive article
-- - excludes NULL embedding
-- - exposes source, title, text, score
WITH query_vector AS (
  SELECT array_fill(0.1, ARRAY[1536])::vector AS embedding
)
SELECT
  a.source AS source,
  a.title AS title,
  c.chunk_text AS text,
  1 - (c.embedding <=> q.embedding) AS score
FROM article_chunks c
JOIN articles a ON a.id = c.article_id
CROSS JOIN query_vector q
WHERE c.domain_id = '00000000-0000-0000-0000-000000000101'
  AND c.embedding IS NOT NULL
  AND a.status = 'active'
ORDER BY c.embedding <=> q.embedding, c.id
LIMIT 3;

WITH query_vector AS (
  SELECT array_fill(0.1, ARRAY[1536])::vector AS embedding
),
actual_results AS (
  SELECT
    c.domain_id,
    a.status,
    a.source,
    a.title,
    c.chunk_text AS text,
    1 - (c.embedding <=> q.embedding) AS score
  FROM article_chunks c
  JOIN articles a ON a.id = c.article_id
  CROSS JOIN query_vector q
  WHERE c.domain_id = '00000000-0000-0000-0000-000000000101'
    AND c.embedding IS NOT NULL
    AND a.status = 'active'
  ORDER BY c.embedding <=> q.embedding, c.id
  LIMIT 3
)
SELECT COUNT(*) AS expected_domain_a_rows
FROM actual_results;

-- Expected count: 0
WITH query_vector AS (
  SELECT array_fill(0.1, ARRAY[1536])::vector AS embedding
),
actual_results AS (
  SELECT
    c.domain_id,
    a.status,
    a.source,
    a.title,
    c.chunk_text AS text,
    1 - (c.embedding <=> q.embedding) AS score
  FROM article_chunks c
  JOIN articles a ON a.id = c.article_id
  CROSS JOIN query_vector q
  WHERE c.domain_id = '00000000-0000-0000-0000-000000000101'
    AND c.embedding IS NOT NULL
    AND a.status = 'active'
  ORDER BY c.embedding <=> q.embedding, c.id
  LIMIT 3
)
SELECT COUNT(*) AS should_exclude_other_domains
FROM actual_results
WHERE domain_id <> '00000000-0000-0000-0000-000000000101';

-- Expected count: 0
WITH query_vector AS (
  SELECT array_fill(0.1, ARRAY[1536])::vector AS embedding
),
actual_results AS (
  SELECT
    c.domain_id,
    a.status,
    a.source,
    a.title,
    c.chunk_text AS text,
    1 - (c.embedding <=> q.embedding) AS score
  FROM article_chunks c
  JOIN articles a ON a.id = c.article_id
  CROSS JOIN query_vector q
  WHERE c.domain_id = '00000000-0000-0000-0000-000000000101'
    AND c.embedding IS NOT NULL
    AND a.status = 'active'
  ORDER BY c.embedding <=> q.embedding, c.id
  LIMIT 3
)
SELECT COUNT(*) AS should_exclude_inactive_articles
FROM actual_results
WHERE status <> 'active';

-- Expected count: 0
WITH query_vector AS (
  SELECT array_fill(0.1, ARRAY[1536])::vector AS embedding
),
actual_results AS (
  SELECT
    c.domain_id,
    a.status,
    a.source,
    a.title,
    c.chunk_text AS text,
    1 - (c.embedding <=> q.embedding) AS score
  FROM article_chunks c
  JOIN articles a ON a.id = c.article_id
  CROSS JOIN query_vector q
  WHERE c.domain_id = '00000000-0000-0000-0000-000000000101'
    AND c.embedding IS NOT NULL
    AND a.status = 'active'
  ORDER BY c.embedding <=> q.embedding, c.id
  LIMIT 3
)
SELECT COUNT(*) AS should_expose_contract_shape
FROM actual_results
WHERE source IS NULL
   OR title IS NULL
   OR text IS NULL
   OR score IS NULL;

-- Expected count: 0
SELECT COUNT(*) AS should_exclude_null_embeddings
FROM article_chunks c
JOIN articles a ON a.id = c.article_id
WHERE c.domain_id = '00000000-0000-0000-0000-000000000101'
  AND c.embedding IS NULL
  AND a.status = 'active';

ROLLBACK;
