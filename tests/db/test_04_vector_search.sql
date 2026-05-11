-- Teste 04 - Busca Vetorial
-- Verifica se o pgvector retorna chunks por similaridade
-- Esperado: chunk_text = 'texto de teste', similarity = 1

INSERT INTO domains (id, name, display_name)
VALUES ('00000000-0000-0000-0000-000000000001', 'test-domain', 'Teste')
ON CONFLICT (name) DO NOTHING;

INSERT INTO articles (id, domain_id, title, source, content_hash)
VALUES (
  '00000000-0000-0000-0000-000000000002',
  '00000000-0000-0000-0000-000000000001',
  'Artigo Teste', 'test.md',
  md5('conteudo teste')
) ON CONFLICT DO NOTHING;

INSERT INTO article_chunks
  (article_id, domain_id, chunk_index, chunk_text, content_hash, embedding)
VALUES (
  '00000000-0000-0000-0000-000000000002',
  '00000000-0000-0000-0000-000000000001',
  0, 'texto de teste', md5('texto de teste'),
  array_fill(0.1, ARRAY[1536])::vector
) ON CONFLICT DO NOTHING;

SELECT chunk_text,
  1 - (embedding <=> array_fill(0.1, ARRAY[1536])::vector) AS similarity
FROM article_chunks
WHERE domain_id = '00000000-0000-0000-0000-000000000001'
ORDER BY embedding <=> array_fill(0.1, ARRAY[1536])::vector
LIMIT 1;

-- Limpa
DELETE FROM domains WHERE id = '00000000-0000-0000-0000-000000000001';