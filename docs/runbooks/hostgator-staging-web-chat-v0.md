# Runbook - HostGator Staging Web Chat V0

## Objetivo

Registrar o bloco minimo de variaveis de ambiente e o checklist de smoke para
ligar com seguranca a V0 publica do chat web no staging HostGator.

Este runbook cobre apenas a superficie publica controlada do website:

- `GET /chat-ui`
- `POST /web/chat`
- `POST /web/feedback`

Nao substitui os runbooks de:

- smoke HTTP geral
- pgvector
- WhatsApp

Se a UI publica for o `ask-host-genius`, use tambem
`docs/runbooks/chat-ordens-frontend-proxy.md`. Nesse modelo, o Nginx sobrepoe
`/chat-ui` com o frontend separado e mantem `/web/*` apontando para este
backend.

## Escopo

Usar este runbook quando o objetivo for:

- habilitar a `chat-ui` publica no staging
- validar sessao anonima por cookie
- confirmar que o navegador nao precisa de `X-API-Key`
- limitar risco inicial de abuso e custo

## Variaveis Recomendadas

Bloco base para staging:

```dotenv
APP_NAME=supportFAQagent
APP_ENV=staging

DEFAULT_DOMAIN=suporte-vps-whatsapp
DOMAINS_PATH=domains

API_SECRET_KEY=trocar-por-secret-forte-e-unico
OPENAI_API_KEY=trocar-por-chave-privada-real
ANTHROPIC_API_KEY=
PROJECT_LLM_API_KEY_ALIAS=

DATABASE_URL=trocar-por-database-url-privada
RETRIEVAL_BACKEND=pgvector

RATE_LIMIT_PER_MINUTE=30

ENABLE_CHAT_UI=false
ENABLE_PUBLIC_CHAT_UI=true
WEB_CHAT_RATE_LIMIT_PER_MINUTE=10
WEB_CHAT_SESSION_COOKIE=sfaq_web_session_staging
WEB_CHAT_COOKIE_SECURE=true

RECALL_API_KEY=
ZOOM_WEBHOOK_SECRET=
```

## Motivo Dos Valores

- `ENABLE_PUBLIC_CHAT_UI=true`
  - expoe a V0 publica do website
- `ENABLE_CHAT_UI=false`
  - evita reabrir o atalho legado baseado em `X-LLM-API-Key`
- `WEB_CHAT_COOKIE_SECURE=true`
  - obrigatorio fora de desenvolvimento para proteger a sessao anonima
- `WEB_CHAT_RATE_LIMIT_PER_MINUTE=10`
  - baseline conservador para reduzir abuso e custo inicial
- `WEB_CHAT_SESSION_COOKIE=sfaq_web_session_staging`
  - evita confundir sessao entre ambientes
- `RATE_LIMIT_PER_MINUTE=30`
  - separa o consumo dos endpoints internos protegidos do limite publico do website
- `RETRIEVAL_BACKEND=pgvector`
  - usar quando o staging oficial ja estiver com `DATABASE_URL`, embeddings e dados ingeridos

## Pre-Requisitos

- staging atras de HTTPS valido
- runtime com `API_SECRET_KEY` privado
- runtime com `OPENAI_API_KEY` privado se a validacao usar provider real
- `DATABASE_URL` privado apontando para o PostgreSQL oficial do staging
- dados do dominio inicial ja ingeridos se `RETRIEVAL_BACKEND=pgvector`

## Regras De Hardening

- nao usar `ENABLE_CHAT_UI=true` junto com a superficie publica do website
- nao usar `WEB_CHAT_COOKIE_SECURE=false` em staging
- nao deixar `WEB_CHAT_RATE_LIMIT_PER_MINUTE=0`
- nao compartilhar cookie name de staging com outros ambientes
- nao expor `API_SECRET_KEY`, `OPENAI_API_KEY` ou `DATABASE_URL` em logs, PRs ou docs

## Checklist Antes De Subir

- `API_SECRET_KEY` foi definido com valor forte e unico
- `ENABLE_PUBLIC_CHAT_UI=true`
- `ENABLE_CHAT_UI=false`
- `WEB_CHAT_COOKIE_SECURE=true`
- `WEB_CHAT_RATE_LIMIT_PER_MINUTE=10`
- `WEB_CHAT_SESSION_COOKIE=sfaq_web_session_staging`
- staging esta atras de HTTPS
- `RETRIEVAL_BACKEND` confere com o estado real do ambiente

## Smoke Rapido

### 1. Confirmar a UI publica

```bash
curl -i https://staging.example/chat-ui
```

Esperado:

- `200`
- HTML com o titulo do chat
- sem campo pedindo API key do provider

### 2. Confirmar o chat publico

```bash
curl -i \
  -H "Content-Type: application/json" \
-d '{"message":"Como conectar o WhatsApp pela Meta API oficial?"}' \
  https://staging.example/web/chat
```

Esperado:

- `200`
- header `X-Request-ID`
- cookie de sessao anonima
- body com `request_id`, `answer`, `support_code`, `escalated`, `handoff_reasons`, `references`, `error_code`
- sem necessidade de `X-API-Key`

### 3. Confirmar o feedback publico

Reenviar o `request_id` da etapa anterior preservando o cookie de sessao:

```bash
curl -i \
  -H "Content-Type: application/json" \
  -b "sfaq_web_session_staging=<cookie-retornado>" \
  -d '{"request_id":"<uuid-do-chat>","helpful":true,"reason":"resolved","comment":"Smoke staging"}' \
  https://staging.example/web/feedback
```

Esperado:

- `200`
- body com `accepted=true`
- `storage=postgres` quando `PERSISTENCE_BACKEND=postgres`
- `storage=pending_persistence` apenas quando a persistencia estiver
  intencionalmente desativada

## O Que Verificar No Browser

- a pagina abre sem campo de API key
- requests saem para `/web/chat` e `/web/feedback`
- requests nao enviam `X-API-Key`
- requests nao enviam `X-LLM-API-Key`
- resposta de erro mostra codigo de suporte
- quando houver escalonamento, a UI sinaliza isso de forma amigavel

## O Que Verificar Nos Logs

- existe `X-Request-ID` por request
- evento `web_chat_completed` aparece com:
  - `request_id`
  - `session_id_hash`
  - `retrieval_backend`
  - `references_count`
  - `total_ms`
  - `retrieval_ms`
  - `llm_ms`
- nenhum log contem cookie bruto, `session_id` bruto, segredo ou payload sensivel

## Sinais De Bloqueio

Interrompa a exposicao da V0 publica se ocorrer qualquer um destes:

- cookie publico saindo sem `Secure` em staging
- `/chat-ui` exigir ou sugerir API key do provider
- browser enviando `X-API-Key` ou `X-LLM-API-Key`
- `WEB_CHAT_RATE_LIMIT_PER_MINUTE=0` ou ausente por override indevido
- respostas frequentes com `429` mesmo em uso normal
- custo de provider subindo acima do tolerado para o volume esperado

## Referencias

- [Mapa oficial de ambientes](../environments.md)
- [Contratos de integracao](../integration-contracts.md)
- [Smoke HTTP automatizado em staging](staging-http-smoke.md)
- [Plano arquivado V0 do chat web](../archive/implementation-plans/web-chat-v0-implementation-plan.md)
