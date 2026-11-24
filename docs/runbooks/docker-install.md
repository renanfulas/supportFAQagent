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
| `deploy/install.sh` | Instalacao guiada: gera o `.env`, sobe, registra dominios, cadastra o operador, roda evals e smoke, grava o relatorio |
| `deploy/docker-smoke.sh` | Smoke do pacote num projeto descartavel (o mesmo que roda no CI) |
| `.github/workflows/docker-image.yml` | Build + smoke em todo PR; publica a imagem versionada no GHCR em tag `vX.Y.Z` |

A guarda `tests/test_docker_packaging.py` falha se alguma dessas regras mudar
(porta publica, segredo literal, usuario root, `.env` no contexto de build).
`tests/test_docker_image_workflow.py` guarda o caminho de release (publicar so
em tag, imagem publicada = imagem testada, sem `latest`).

## Usar a imagem publicada (sem build na maquina do cliente)

Cada tag `vX.Y.Z` publica `ghcr.io/renanfulas/supportfaqagent:X.Y.Z` e
`:X.Y`, a mesma imagem que passou no smoke do CI. Nao existe `latest`: a
instalacao sempre fixa a versao. No `.env`:

```bash
SUPPORTFAQ_IMAGE=ghcr.io/renanfulas/supportfaqagent:0.1.0
```

E subir sem build:

```bash
docker compose -f docker-compose.prod.yml pull app
docker compose -f docker-compose.prod.yml up -d --no-build
```

O pacote no GHCR nasce privado. Para o cliente baixar: ou um token de leitura
(`read:packages`) com `docker login ghcr.io` na maquina dele, ou tornar o pacote
publico nas configuracoes do GitHub. A imagem nao carrega segredo nem dado de
cliente, mas carrega o `domains/` padrao do repositorio; o pacote do cliente
continua montado por fora (`CLIENT_PACK_DIR`).

## Pre-requisitos

- Docker Engine com `docker compose` v2.20 ou mais novo (usa `depends_on.required`).
- Um reverse proxy com HTTPS na frente (Caddy, Nginx, Traefik ou o do provedor).
  A API so escuta em `127.0.0.1`; nada fica exposto sem o proxy.
- O pacote do cliente: uma pasta com os dominios e o `installation.yaml` opcional
  (ver [domain-contract.md](../architecture/domain-contract.md)). Sem pasta
  propria, o compose usa o `domains/` do repositorio.

## Instalacao guiada (recomendado)

Um comando faz os passos 1 a 4 abaixo e grava `install-report.md`:

```bash
bash deploy/install.sh --client-pack /srv/acme-pack   --admin-phone +5511999999999 --admin-name "Nome do operador"
```

1. Gera o `.env` com valores aleatorios e privados (`chmod 600`). Um `.env` que
   ja existe nunca e sobrescrito: o script reaproveita e so confere se nao sobrou
   `<set-private-value>`.
2. Sobe a stack. O start seguro migra o banco novo e espera o readiness.
3. Roda `scripts.post_install` no container:
   - registra todos os dominios do pacote na tabela `domains` (sem chave de embedding),
     entao a conversa ja e gravada no primeiro turno;
   - cadastra o primeiro operador do console, se `--admin-phone`/`--admin-name`
     vierem (o relatorio mostra so os 4 ultimos digitos);
   - roda os evals de confinamento de cada dominio (`evals/cases.yaml` e
     `evals/confinement/*`). Eles nao dependem da chave do LLM.
4. Smoke HTTP (`/health`, `/health/ready`, `/domains`, `/chat`) e relatorio.

O relatorio lista passos, dominios, evals e proximos passos (chave de LLM,
pgvector, chat publico, console). Ele nao tem segredo, URL do banco, telefone
completo nem `session_id`, e fica fora do Git. Saida: `0` ok, `1` falhou,
`2` argumento ou configuracao invalida, `3` instalada com eval falhando.

Pode rodar de novo a qualquer momento (ex.: depois de trocar o pacote do cliente):
reaproveita `.env` e banco, registra dominios novos e refaz evals e smoke. Nunca
apaga volume nem dado. `--skip-evals` pula os evals.

As secoes abaixo descrevem os mesmos passos feitos a mao.

## 1. Configurar

```bash
cp deploy/production.env.example .env
```

Preencher no `.env`, com valores aleatorios e privados por ambiente:

- `API_SECRET_KEY`: obrigatoria fora de desenvolvimento; sem ela a API nao sobe.
- `POSTGRES_PASSWORD` e a mesma senha dentro de `DATABASE_URL`.
- `IDENTITY_HASH_SECRET`: chave do hash de telefone dos operadores do console.
  Trocar depois obriga a recadastrar cada operador.
- `PERSISTENCE_HASH_SECRET`: chave do hash de sessao. Defina antes do primeiro
  start e nao troque depois (o bootstrap grava a impressao dela no banco).
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
docker compose -f docker-compose.prod.yml logs app
```

O `app` so inicia depois que o `postgres` estiver saudavel. O container nao chama
o uvicorn direto: ele passa antes pelo start seguro (`scripts/safe_start.py`):

1. Carrega a configuracao. Configuracao invalida (ex.: sem `API_SECRET_KEY`)
   encerra o container com `configuration is invalid`.
2. Com `STARTUP_MIGRATIONS=auto` (padrao), **banco novo e vazio** recebe as
   migrations na mesma sequencia do gate de CI (`.github/workflows/phase0-gates.yml`),
   sob advisory lock: duas replicas subindo juntas nao brigam, e a segunda so
   le o estado depois que a primeira terminou.
3. Espera o readiness passar (`degraded` e aceito) por ate
   `STARTUP_READINESS_TIMEOUT_SECONDS` (padrao 60). Se nao passar, o container
   sai com um resumo dos componentes indisponiveis e o `restart` tenta de novo.
4. So entao faz `exec` do uvicorn, que passa a receber os sinais do container.

No log, o esperado no primeiro boot e:

```text
safe_start: new database detected; applying the bootstrap migrations
safe_start: bootstrap migrations applied
safe_start: readiness passed; starting the API
```

Para checar sem servir (preflight do operador, mesma configuracao):

```bash
docker compose -f docker-compose.prod.yml run --rm app python -m scripts.safe_start --check
```

## 3. Migrations

O start so migra banco **novo**. Ele recusa, sem tocar no schema:

- banco com tabelas e sem ledger de migrations: rodar `python -m scripts.migrate baseline`
  manualmente antes;
- banco ainda antes da migration 007 que ja tem conversas gravadas: seguir o fluxo
  com snapshot e expand/contract de [phase0-snapshot-restore.md](phase0-snapshot-restore.md).

Banco que ja passou do bootstrap **nunca e migrado no start**, nem quando a
versao nova traz migration nova. Nesse caso o readiness acusa
`migrations(pending=N)` e o app nao sobe ate o operador aplicar, com snapshot:

```bash
docker compose -f docker-compose.prod.yml run --rm app python -m scripts.migrate status
docker compose -f docker-compose.prod.yml run --rm app python -m scripts.migrate apply
docker compose -f docker-compose.prod.yml run --rm app python -m scripts.migrate verify
```

`STARTUP_MIGRATIONS=off` desliga ate o bootstrap de banco novo (ex.: banco
gerenciado que o time de dados migra por fora). O readiness continua barrando o
start com migration pendente.

O `PERSISTENCE_HASH_SECRET` precisa estar no `.env` antes do primeiro start: o
bootstrap grava a impressao dele no banco e recusa rodar sem ele. Nao troque
esse valor depois.

## 3b. Registrar os dominios no banco

A conversa so e gravada para dominios que existem na tabela `domains`. A
instalacao guiada registra todos os dominios do pacote; a mao, o mesmo passo e:

```bash
docker compose -f docker-compose.prod.yml run --rm -T app python -m scripts.post_install --skip-evals
```

Ele e idempotente: rodar de novo depois de acrescentar um dominio ao pacote so
registra o novo. A ingestao no pgvector (`scripts.ingest_domain_pgvector`)
tambem registra o dominio que ingere, mas exige a chave de embedding.

## 4. Smoke

Antes de instalar no cliente (ou para reproduzir o CI), o smoke completo roda num
projeto descartavel, com segredos aleatorios de uso unico, e apaga tudo no fim:

```bash
bash deploy/docker-smoke.sh                                       # builda a imagem
SUPPORTFAQ_IMAGE=ghcr.io/renanfulas/supportfaqagent:0.1.0 bash deploy/docker-smoke.sh
```

Ele se recusa a rodar se ja existir um `.env` na raiz e so apaga volumes de
projeto com prefixo `sfaq-smoke`, entao nao toca numa instalacao real. Na
instalacao em si, a checagem manual e:

```bash
curl -i http://127.0.0.1:8000/health
curl -i -H "X-API-Key: $API_SECRET_KEY" http://127.0.0.1:8000/domains
curl -i -H "X-API-Key: $API_SECRET_KEY" http://127.0.0.1:8000/health/ready
```

Esperado:

- `/health`: `200` com `{"status":"ok"}`. E o mesmo endpoint do healthcheck do container.
- `/domains`: os dominios do pacote do cliente. Fora de desenvolvimento exige `X-API-Key`.
- `/health/ready`: `200`. Se o app esta no ar, o readiness ja passou no start;
  um `503` depois disso indica que algo caiu em runtime (ex.: o banco).
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

Se a versao nova trouxer migration, o app novo nao sobe ate ela ser aplicada
pelo passo 3; enquanto isso o `restart` fica tentando e o log mostra
`migrations(pending=N)`. Aplique com snapshot e o proximo restart sobe.

Para voltar: fazer checkout da versao anterior e repetir o `up -d --build`. O
volume `supportfaq_pgdata` nao e tocado. Migration nova so sobe pelo passo 3,
nunca sozinha. Com imagem publicada, trocar a tag de `SUPPORTFAQ_IMAGE` (para
frente ou para tras) e rodar `pull app` + `up -d --no-build`, em vez de rebuildar.

## Publicar uma versao

1. Subir `version` no `pyproject.toml` (semver) num PR e fazer merge na `main`.
2. Criar e enviar a tag igual a versao: `git tag v0.2.0 && git push origin v0.2.0`.
3. O workflow `Docker image` builda, roda o smoke e so entao publica `0.2.0` e
   `0.2`. Tag diferente da versao do `pyproject.toml` falha antes de publicar.

Nunca rodar `docker compose down -v` em producao: o `-v` apaga o volume do banco.

## Fora desta fatia

- Gerar o primeiro dominio do cliente pelo `install.sh` (hoje: `python -m scripts.new_domain`
  no checkout, antes de instalar; ver [fde-engagement-playbook.md](fde-engagement-playbook.md)).
- Perfis de configuracao e `config validate`.
