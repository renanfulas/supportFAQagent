-- Teste 01 - Extensoes
-- Verifica se pgvector e pgcrypto estao habilitados
-- Esperado: 2 registros (vector e pgcrypto)

SELECT extname FROM pg_extension
WHERE extname IN ('vector', 'pgcrypto');