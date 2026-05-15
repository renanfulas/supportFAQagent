-- Validate pgvector top-k retrieval with domain isolation

SELECT
  a.source AS source,
  a.title AS title,
  c.chunk_text AS text,
  1 - (c.embedding <=> ('[' || array_to_string(array_fill(0.1::float8, ARRAY[1536]), ',') || ']')::vector) AS score
FROM article_chunks c
JOIN articles a ON a.id = c.article_id
WHERE c.domain_id = :domain_id
  AND c.embedding IS NOT NULL
  AND a.status = 'active'
ORDER BY c.embedding <=> ('[' || array_to_string(array_fill(0.1::float8, ARRAY[1536]), ',') || ']')::vector
LIMIT :top_k;