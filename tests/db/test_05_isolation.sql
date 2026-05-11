-- Teste 05 - Isolamento por Dominio
-- Verifica que chunks de um dominio nao aparecem em outro
-- Esperado: COUNT = 0

INSERT INTO domains (id, name, display_name) VALUES
  ('00000000-0000-0000-0000-000000000010', 'dominio-a', 'Dominio A'),
  ('00000000-0000-0000-0000-000000000011', 'dominio-b', 'Dominio B')
ON CONFLICT (name) DO NOTHING;

SELECT COUNT(*) FROM article_chunks
WHERE domain_id = '00000000-0000-0000-0000-000000000010';

-- Limpa
DELETE FROM domains WHERE id IN (
  '00000000-0000-0000-0000-000000000010',
  '00000000-0000-0000-0000-000000000011'
);