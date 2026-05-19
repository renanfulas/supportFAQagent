# Mapa Oficial de Ambientes

Este documento define qual ambiente vale como referencia oficial para banco, pgvector, runtime e integracoes externas do `supportFAQagent`.

## Objetivo

Eliminar ambiguidade entre laboratorio local, ambientes externos nao oficiais e o ambiente oficial do projeto antes de ligar o backend ao PostgreSQL + pgvector.

## Regra principal

- Cada ambiente do `supportFAQagent` deve ter um PostgreSQL oficial.
- O backend deve acessar o banco apenas via `DATABASE_URL`.
- O `pgvector` fica no mesmo PostgreSQL da aplicacao, nao em banco separado.
- Nenhum segredo real deve aparecer em Git, PR, docs ou conversa.
- Credenciais ja expostas devem ser tratadas como comprometidas e rotacionadas.

## Ambientes

### Local dev

- Tipo: laboratorio de desenvolvimento e validacao tecnica.
- Banco: Docker com `pgvector/pgvector:pg16`.
- Uso esperado:
  - validar migration `001_initial_schema.sql`
  - validar extensoes `vector` e `pgcrypto`
  - validar inserts e query top-k
  - validar scripts em `tests/db/`
- Status: descartavel, pode ser recriado sem impacto operacional.

### Staging HostGator

- Tipo: ambiente oficial de staging do projeto.
- Banco: PostgreSQL oficial do `supportFAQagent` na HostGator.
- `pgvector`: no mesmo banco da aplicacao.
- Provisionamento: a definir com Silotto.
- Status: ambiente oficial para conectar backend e validar operacao real.

### Producao HostGator

- Tipo: ambiente oficial futuro.
- Banco: PostgreSQL oficial do `supportFAQagent` em producao.
- `pgvector`: no mesmo banco da aplicacao.
- Status: fora de provisao nesta frente.

### Hostinger/EasyPanel

- Tipo: laboratorio externo.
- Uso aceito:
  - testes locais ou paralelos de SQL
  - validacao exploratoria de runtime
- Uso proibido:
  - fonte de verdade do projeto
  - referencia oficial de nomes de banco, URL, Adminer, credenciais ou topologia
- Status: nao oficial.

### n8n

- Tipo: consumidor externo da API do backend.
- Interface oficial:
  - `POST /chat`
  - `POST /feedback`
  - futuros contratos HTTP do backend
- Regras:
  - deve preservar `X-Request-ID`, `request_id`, `handoff_reasons`, `references` e `error_code`
  - nao deve acessar diretamente as tabelas internas do RAG
  - nao deve carregar regra central de inteligencia
- Pode coexistir em Docker com `supportfaq_api`, desde que seja um servico
  separado e reversivel.
- Desabilitar temporariamente o `n8n` nao deve derrubar a API, apagar banco ou
  remover volumes de workflow.
- Desabilitar temporariamente a API nao deve apagar o PostgreSQL/pgvector nem os
  dados da Evolution.

## Responsabilidades por frente

- Alexandre: schema SQL, migrations, query vetorial, persistencia real, validacao PostgreSQL.
- Renan: contratos, adapter Python, testes do backend, documentacao de ambiente, seguranca e integracao com `/chat`.
- Silotto: provisionamento oficial na HostGator, runtime, secrets e conectividade.
- Juliano: fora desta frente, salvo impacto indireto em embeddings ou splitter.

## Validacao esperada

Para gate de SQL e pgvector, usar ambiente deterministico sem depender de provider real.

```powershell
psql $env:DATABASE_URL -f migrations/001_initial_schema.sql
psql $env:DATABASE_URL -f tests/db/test_01_extensions.sql
psql $env:DATABASE_URL -f tests/db/test_02_schema.sql
psql $env:DATABASE_URL -f tests/db/test_03_idempotency.sql
psql $env:DATABASE_URL -f tests/db/test_04_vector_search.sql
psql $env:DATABASE_URL -f tests/db/test_05_isolation.sql
psql $env:DATABASE_URL -f tests/db/validate_pgvector_search.sql
```

Os domain evals usados como gate desta frente devem rodar com fallback deterministico, nao com provider real bloqueando a validacao de banco:

```powershell
python -m pytest
python -m app.evals.run_domain_eval suporte-vps-whatsapp
```

## Proximo encaixe

Depois deste alinhamento:

1. Alexandre fecha banco oficial, migrations e query vetorial.
2. Renan conecta o backend ao PostgreSQL/pgvector pelo contrato `PgVectorStore`.
3. `n8n` entra depois, consumindo a API HTTP em vez do banco do agente.
