-- Teste 02 - Schema
-- Verifica se todas as tabelas existem
-- Esperado: 5 registros

SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
AND table_name IN (
  'domains', 'articles', 'article_chunks',
  'conversations', 'messages'
);

-- Verifica se coluna embedding tem tipo correto
-- Esperado: udt_name = 'vector'

SELECT column_name, udt_name
FROM information_schema.columns
WHERE table_name = 'article_chunks'
AND column_name = 'embedding';