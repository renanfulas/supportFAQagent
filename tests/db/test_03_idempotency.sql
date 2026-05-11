-- Teste 03 - Idempotencia
-- Verifica que o mesmo conteudo nao cria duplicacao
-- Esperado: COUNT = 1

INSERT INTO domains (name, display_name)
VALUES ('test-domain', 'Dominio de Teste')
ON CONFLICT (name) DO NOTHING;

INSERT INTO domains (name, display_name)
VALUES ('test-domain', 'Dominio de Teste')
ON CONFLICT (name) DO NOTHING;

SELECT COUNT(*) FROM domains
WHERE name = 'test-domain';

-- Limpa
DELETE FROM domains WHERE name = 'test-domain';