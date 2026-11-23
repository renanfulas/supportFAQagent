# Runbook - Instalacao via Docker (uma instalacao por empresa)

Este runbook sobe o `supportFAQagent` numa maquina nova com Docker, para uma
empresa (single-tenant). Ele empacota o que ja existe: a mesma API, as mesmas
migrations e os mesmos scripts operacionais, dentro de uma imagem versionavel.

Ele **nao substitui** o deploy atual do staging HostGator
([vps-controlled-runtime.md](vps-controlled-runtime.md)). Trocar aquele deploy
pela imagem e uma decisao separada, com snapshot e janela propria.

## O que vem no pacote

| Arquivo | Papel |
| --- | --- |
| `Dockerfile` | Imagem Python 3.11, dependencias lidas do `pyproject.toml`, usuario nao-root, healthcheck em `/health` |
| `.dockerignore` | Allowlist: so `app/`, `scripts/`, `migrations/`, `domains/` e `pyproject.toml` entram no build; `.env` e chaves nunca |
| `docker-compose.prod.yml` | `app` + `postgres` (pgvector, perfil `db`) + `redis` (perfil `redis`, opcional) |
| `deploy/production.env.example` | Configuracao minima da instalacao |

A guarda `tests/test_docker_packaging.py` falha se alguma dessas regras mudar
(porta publica, segredo literal, usuario root, `.env` no contexto de build).

## Pre-requisitos

- Docker Engine com `docker compose` v2.20 ou mais novo (usa `depends_on.required`).
- Um reverse proxy com HTTPS na frente (Caddy, Nginx, Traefik ou o do provedor).
  A API so escuta em `127.0.0.1`; nada fica exposto sem o proxy.
- O pacote do cliente: uma pasta com os dominios e o `installation.yaml` opcional
  (ver [domain-contract.md](../architecture/domain-contract.md)). Sem pasta
  propria, o compose usa o `domains/` do repositorio.

## 1. Configurar

```bash
cp deploy/production.env.example .env
```

Preencher no `.env`, com valores aleatorios e privados por ambiente:

- `API_SECRET_KEY`: obrigatoria fora de desenvolvimento; sem ela a API nao sobe.
- `POSTGRES_PASSWORD` e a mesma senha dentro de `DATABASE_URL`.
- `PERSISTENCE_HASH_SECRET`: chave do hash de sessao. Defina antes das
  migrations e nao troque depois (o passo 3 grava a impressao dela no banco).
- `CLIENT_PACK_DIR`: caminho da pasta do pacote do cliente.
- `OPENAI_API_KEY` ou `ANTHROPIC_API_KEY`: sem chave, o chat responde com o
  fallback seguro `provider_error`.
- `FORWARDED_ALLOW_IPS`: IP do reverse proxy como o container o ve. Sem isso,
  todos os clientes parecem ter o mesmo IP e dividem o mesmo rate limit.

Com banco gerenciado externo: tirar `db` de `COMPOSE_PROFILES` e apontar
`DATABASE_URL` para ele. O banco precisa das extensoes `vector` e `pgcrypto`.

## 2. Subir

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
```

O `app` so inicia depois que o `postgres` estiver saudavel.

## 3. Aplicar as migrations (instalacao nova)

O pacote **nao migra sozinho no start**. Em banco novo e vazio, a sequencia e a
mesma do gate de CI (`.github/workflows/phase0-gates.yml`). A migration 007 so
passa depois que o contrato de privacidade e marcado com o
`PERSISTENCE_HASH_SECRET` definitivo da instalacao, entao defina esse valor no
`.env` antes deste passo e nao troque depois:

```bash
docker compose -f docker-compose.prod.yml run --rm app python -m scripts.migrate apply --target 006_conversations_messages.sql
docker compose -f docker-compose.prod.yml run --rm app python -m scripts.backfill_conversation_privacy --verify-contract-ready --quiet-period-seconds 0
docker compose -f docker-compose.prod.yml run --rm app python -m scripts.migrate apply
docker compose -f docker-compose.prod.yml run --rm app python -m scripts.migrate verify
```

O `--quiet-period-seconds 0` so vale para banco vazio. Em banco que ja tem dados,
seguir o fluxo com snapshot e expand/contract de
[phase0-snapshot-restore.md](phase0-snapshot-restore.md) antes de qualquer `apply`.

Depois das migrations, ligar a persistencia no `.env` (`PERSISTENCE_BACKEND=postgres`)
e recriar o app:

```bash
docker compose -f docker-compose.prod.yml up -d app
```

## 3b. Registrar os dominios no banco

A conversa so e gravada para dominios que ja existem na tabela `domains`, e hoje
quem cria essa linha e a ingestao no pgvector, que precisa da chave do provider de
embedding do dominio (`embedding` no `domain.yaml`):

```bash
docker compose -f docker-compose.prod.yml run --rm app python -m scripts.ingest_domain_pgvector --domain <dominio>
```

Sem esse passo o chat continua respondendo, mas cada turno registra
`chat_persistence_unavailable` no log e a conversa nao e gravada (fail-open).

## 4. Smoke

```bash
curl -i http://127.0.0.1:8000/health
curl -i -H "X-API-Key: $API_SECRET_KEY" http://127.0.0.1:8000/domains
curl -i -H "X-API-Key: $API_SECRET_KEY" http://127.0.0.1:8000/health/ready
```

Esperado:

- `/health`: `200` com `{"status":"ok"}`. E o mesmo endpoint do healthcheck do container.
- `/domains`: os dominios do pacote do cliente. Fora de desenvolvimento exige `X-API-Key`.
- `/health/ready`: `200` depois que a persistencia estiver ligada. Antes disso
  ele responde `503` com `postgres_required`, porque fora de desenvolvimento o
  runtime exige Postgres. Isso e esperado no primeiro boot.
- `/chat-ui` responde `404` em producao ate `ENABLE_PUBLIC_CHAT_UI=true`, que
  exige cookie seguro e o reverse proxy com HTTPS (ver
  [environments.md](../setup/environments.md)).

## 5. Operacao

Os scripts rodam como tarefa avulsa no mesmo container, com a mesma configuracao:

```bash
docker compose -f docker-compose.prod.yml run --rm app python -m scripts.check_readiness
docker compose -f docker-compose.prod.yml run --rm app python -m scripts.manage_staff list
docker compose -f docker-compose.prod.yml run --rm app python -m scripts.dispatch_outbox --once
docker compose -f docker-compose.prod.yml run --rm app python -m scripts.ingest_domain_pgvector --domain <dominio>
```

Agendamento (outbox, resumo noturno, retencao) continua por timer do host, como em
[conversation-summary-batch.md](conversation-summary-batch.md), chamando o
`docker compose ... run --rm app ...` em vez do venv. Um servico de worker no
compose fica para a proxima fatia.

Arquivos que o app grava (ex.: sink NDJSON de arquivo) devem apontar para
`/var/lib/supportfaq`, o unico volume gravavel do container. O resto do sistema
de arquivos e somente leitura.

## Atualizar e voltar atras

```bash
git pull --ff-only
docker compose -f docker-compose.prod.yml up -d --build
```

Para voltar: fazer checkout da versao anterior e repetir o `up -d --build`. O
volume `supportfaq_pgdata` nao e tocado. Migration nova so sobe pelo passo 3,
nunca sozinha. Se `SUPPORTFAQ_IMAGE` apontar para uma imagem publicada, trocar a
tag em vez de rebuildar.

Nunca rodar `docker compose down -v` em producao: o `-v` apaga o volume do banco.

## Fora desta fatia

- Imagem publicada e versionada no CI, com smoke dentro do compose.
- Start seguro com readiness antes de aceitar trafego.
- Comando `init` que gera `.env`, migra, cria admin e roda smoke e evals.
- Perfis de configuracao e `config validate`.
