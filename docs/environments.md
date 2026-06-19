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
- Banco: Docker com `pgvector/pgvector:pg16` ou PostgreSQL/pgvector
  descartavel em WSL1 quando virtualizacao nao estiver disponivel.
- Uso esperado:
  - validar o runner e migrations `001-008`
  - validar extensoes `vector` e `pgcrypto`
  - validar expand/contract, concorrencia, privacidade e readiness
  - validar inserts, query top-k e scripts em `tests/db/`
- Status: descartavel, pode ser recriado sem impacto operacional.

### Staging HostGator

- Tipo: ambiente oficial de staging do projeto.
- Banco: PostgreSQL oficial do `supportFAQagent` na HostGator.
- `pgvector`: no mesmo banco da aplicacao.
- Retrieval default: `RETRIEVAL_BACKEND=pgvector`.
- Rollback de retrieval: `RETRIEVAL_BACKEND=lexical`, sem apagar dados
  pgvector.
- Provisionamento e operacao: Juliano, coordenado com Renan para banco,
  migrations e contratos.
- Valores recomendados para a V0 do chat publico:
  - `ENABLE_PUBLIC_CHAT_UI=true`
  - `ENABLE_CHAT_UI=false`
  - `WEB_CHAT_COOKIE_SECURE=true`
  - `WEB_CHAT_RATE_LIMIT_PER_MINUTE=10` como ponto inicial
  - `WEB_CHAT_SESSION_COOKIE=sfaq_web_session_staging`
  - `RATE_LIMIT_PER_MINUTE=30` para consumidores internos, salvo ajuste operacional
- Motivo:
  - `ENABLE_PUBLIC_CHAT_UI` expoe apenas a fachada publica `/web/*`
  - `ENABLE_CHAT_UI=false` evita reabrir o atalho legado baseado em `X-LLM-API-Key`
  - cookie seguro e obrigatorio protege a sessao anonima do website
  - rate limit publico baixo reduz custo e abuso enquanto a V0 ainda nao tem antifraude mais forte
- Status: ambiente oficial para conectar backend e validar operacao real.
  Desde 19/06/2026, o staging opera com pgvector como default de retrieval
  porque readiness, smoke privado e `pgvector_gate.yaml` passaram acima do
  criterio normal.

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

### Integracoes externas futuras

- Tipo: consumidores externos opcionais da API do backend.
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
- `n8n` nao faz mais parte do plano operacional atual do MVP.
- Desabilitar temporariamente a API nao deve apagar o PostgreSQL/pgvector nem os
  dados de qualquer consumidor externo futuro.

### Website chat publico

- Tipo: superficie publica controlada para a V0 do website.
- Interface oficial:
  - `POST /web/chat`
  - `POST /web/feedback`
- Regras:
  - nao envia `X-API-Key` pelo navegador
  - usa sessao anonima por cookie `HttpOnly`
  - em staging e producao, o cookie deve sair com `Secure=true`
  - nao escolhe `domain` livremente no V0
  - preserva `X-Request-ID`, `request_id`, `handoff_reasons`, `references` e `error_code`
  - deve ficar atras de rate limit publico
  - `ENABLE_PUBLIC_CHAT_UI=true` e a flag explicita para expor a `chat-ui` fora do modo de desenvolvimento
- Baseline recomendado de hardening:
  - `WEB_CHAT_RATE_LIMIT_PER_MINUTE=10`
  - nome de cookie por ambiente, por exemplo `sfaq_web_session_staging`
  - reverse proxy com HTTPS obrigatorio antes de liberar acesso externo
- Status: pronto para validacao controlada da V0; nao substitui integracoes WhatsApp ou atendimento humano

## Responsabilidades por frente

- Renan: schema SQL, migrations, query vetorial, persistencia real, contratos,
  testes do backend, seguranca e integracao com `/chat`.
- Juliano: provisionamento oficial, runtime, secrets, conectividade, snapshots
  e recuperacao.

## Validacao esperada

Para gate de SQL e pgvector, usar ambiente deterministico sem depender de
provider real. Migrations novas devem ser aplicadas pelo runner, nao por
execucao manual isolada:

```powershell
python -m scripts.migrate status
python -m scripts.migrate apply --target 006_conversations_messages.sql
python -m scripts.backfill_conversation_privacy --verify-contract-ready
python -m scripts.migrate apply
python -m scripts.migrate verify
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

1. Juliano prepara logs, alertas, snapshot e restore isolado.
2. Renan e Juliano mantem readiness, smoke privado e gate pgvector como
   validacoes recorrentes do staging.
3. Consumidores externos futuros devem consumir a API HTTP, nunca o banco do
   agente.
