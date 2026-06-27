# Configuracao da VPS - supportFAQagent

Guia de instalacao e configuracao do ambiente de staging na nova VPS.
Baseado em `docs/environments.md`, `docs/runbooks/vps-controlled-runtime.md`,
`docs/runbooks/hostgator-staging-web-chat-v0.md` e
`docs/security/vps-security-plan.md`.

Ownership de VPS, deploy, runtime, rede, logs, secrets, restore e
conectividade externa: Juliano. `n8n` foi removido do projeto; a entrega externa
de WhatsApp segue a direcao de Meta WhatsApp Cloud API nativa.
Ownership de banco, migrations, pgvector, contratos, backend e testes: Renan.
Rollout de migration, restore e promocao exigem revisao conjunta.

---

## 1. Pre-requisitos na VPS

```bash
# Python obrigatorio: 3.11+
python3 --version

# Git
git --version

# Docker (para PostgreSQL + pgvector)
docker --version
```

O ultimo staging validado usou Python 3.11.13. Nao usar versao anterior.

---

## 2. Clonar o repositorio

```bash
cd <deploy-root>
git clone <repo-url> supportFAQagent
cd supportFAQagent
git checkout main
git pull --ff-only origin main
```

---

## 3. Ambiente Python

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

---

## 4. Arquivo .env privado

Criar o arquivo `.env` fora do Git. Nunca commitar. Nunca colar valores reais
em issue, PR, chat ou documento publico.

```dotenv
# App
APP_NAME=supportFAQagent
APP_ENV=staging
DEFAULT_DOMAIN=suporte-vps-whatsapp
DOMAINS_PATH=domains

# Auth da API
API_SECRET_KEY=<secret-forte-e-unico>

# Provider LLM
OPENAI_API_KEY=<chave-privada-real>
ANTHROPIC_API_KEY=
PROJECT_LLM_API_KEY_ALIAS=

# Banco
DATABASE_URL=<database-url-privada-do-postgres>
RETRIEVAL_BACKEND=pgvector
PERSISTENCE_BACKEND=postgres
PERSISTENCE_HASH_SECRET=<secret-dedicado>
PERSISTENCE_HASH_VERSION=hmac-sha256-v1
OUTBOX_WEBHOOK_SECRET=<secret-dedicado>
ENABLE_OUTBOX_INGRESS=true
VERIFIED_HANDOFF_WEBHOOK_URL=<url-interna>
VERIFIED_WHATSAPP_WEBHOOK_URL=<url-interna>
VERIFIED_OTP_WEBHOOK_URL=<url-interna>
HANDOFF_WEBHOOK_URL=<url-interna-do-ingress-assinado>
WHATSAPP_MESSAGE_WEBHOOK_URL=<url-interna-do-ingress-assinado>
OTP_DELIVERY_WEBHOOK_URL=<url-interna-do-ingress-assinado>
HEALTH_OUTBOX_READY_DEGRADED_COUNT=100
HEALTH_OUTBOX_OLDEST_READY_DEGRADED_SECONDS=300
OUTBOX_PROCESSING_STALE_SECONDS=300

# Rate limits
RATE_LIMIT_PER_MINUTE=30

# Chat publico V0 website
ENABLE_CHAT_UI=false
ENABLE_PUBLIC_CHAT_UI=true
WEB_CHAT_RATE_LIMIT_PER_MINUTE=10
WEB_CHAT_SESSION_COOKIE=sfaq_web_session_staging
WEB_CHAT_COOKIE_SECURE=true

# WhatsApp OTP V1B
ENABLE_WEB_WHATSAPP_AUTH=true
WEB_AUTH_STORAGE_BACKEND=postgres
IDENTITY_HASH_SECRET=<secret-diferente-do-api-secret>
OTP_DIGEST_SECRET=<secret-diferente-dos-demais>
WEB_AUTH_OTP_DELIVERY_TRANSPORT=<memory|verified_webhook>
VERIFIED_OTP_WEBHOOK_URL=<url-interna-do-webhook-de-entrega>

# Zoom (deixar vazio se nao usar)
RECALL_API_KEY=
ZOOM_WEBHOOK_SECRET=
```

Regras obrigatorias:

- Cada secret deve ser unico — nunca reutilizar entre variaveis
- Credenciais de staging separadas das de producao
- Qualquer credencial compartilhada em conversa deve ser rotacionada imediatamente
- `.env` com permissao restrita no servidor

---

## 5. PostgreSQL e pgvector via Docker

```bash
docker run -d \
  --name supportfaq_db \
  -e POSTGRES_DB=supportfaq \
  -e POSTGRES_USER=<usuario> \
  -e POSTGRES_PASSWORD=<senha> \
  -p 127.0.0.1:5432:5432 \
  pgvector/pgvector:pg16
```

A porta `5432` deve ficar exposta **somente em loopback** (`127.0.0.1`).
Nunca abrir `5432` diretamente para a internet.

---

## 6. Aplicar as migrations

Antes de qualquer migration em staging, criar snapshot e executar o preflight
da Fase 0. Aplicar pelo runner auditavel; nao executar migrations novas
manualmente com `psql`.

```bash
python -m scripts.staging_phase0_preflight \
  --snapshot-confirmed \
  --env-file .env \
  --output /tmp/supportfaq-phase0-preflight.md

python -m scripts.migrate status
python -m scripts.migrate apply --target 006_conversations_messages.sql
python -m scripts.backfill_conversation_privacy
python -m scripts.backfill_conversation_privacy --verify-contract-ready
python -m scripts.migrate apply
python -m scripts.migrate apply
python -m scripts.migrate verify
```

Em banco novo, a confirmacao do backfill continua obrigatoria antes da fase
contract. Em banco onde `001` e `002` foram aplicadas manualmente, use
`baseline` somente depois da validacao exigida pelo runner.

Os testes SQL abaixo continuam validos para o contrato pgvector:

```bash
psql "$DATABASE_URL" -f tests/db/test_01_extensions.sql
psql "$DATABASE_URL" -f tests/db/test_02_schema.sql
psql "$DATABASE_URL" -f tests/db/test_03_idempotency.sql
psql "$DATABASE_URL" -f tests/db/test_04_vector_search.sql
psql "$DATABASE_URL" -f tests/db/test_05_isolation.sql
psql "$DATABASE_URL" -f tests/db/validate_pgvector_search.sql
```

---

## 7. Ingerir o conhecimento do dominio

Obrigatorio para o retrieval pgvector funcionar. Sem isso o chat retorna
`retrieval_error`.

```bash
python scripts/ingest_domain_pgvector.py
```

---

## 8. Validar o ambiente antes de subir

```bash
python -m compileall app tests scripts
python -m pytest
python -m app.evals.run_domain_eval suporte-vps-whatsapp
```

Em Windows ou PowerShell, usar o preflight seguro:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\runtime_preflight.ps1
```

---

## 9. Subir a API em loopback

Sempre comecar em loopback. Nao usar `0.0.0.0` antes do smoke test passar.

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

---

## 10. Smoke tests

Em outra sessao SSH:

```bash
# Saude
curl -i http://127.0.0.1:8000/health

# Readiness operacional
curl -i \
  -H "X-API-Key: $API_SECRET_KEY" \
  http://127.0.0.1:8000/health/ready

# Dominios carregados
curl -i \
  -H "X-API-Key: $API_SECRET_KEY" \
  http://127.0.0.1:8000/domains

# Preview de ingestao
curl -i \
  -H "X-API-Key: $API_SECRET_KEY" \
  http://127.0.0.1:8000/ingestion/suporte-vps-whatsapp/preview

# Chat
curl -i \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_SECRET_KEY" \
  -H "X-Request-ID: smoke-001" \
-d '{"domain":"suporte-vps-whatsapp","session_id":"smoke","message":"Como conectar o WhatsApp pela Meta API oficial?"}' \
  http://127.0.0.1:8000/chat
```

Ou usar o script automatizado:

```bash
export API_SECRET_KEY="<secret-privado>"
python scripts/staging_smoke.py \
  --base-url http://127.0.0.1:8000 \
  --domain suporte-vps-whatsapp \
  --request-id smoke-$(date +%Y%m%d%H%M%S) \
  --output /tmp/smoke-report.md
```

Para validar tambem a fachada publica do website:

```bash
curl -i http://127.0.0.1:8000/chat-ui

curl -i \
  -H "Content-Type: application/json" \
-d '{"message":"Como conectar o WhatsApp pela Meta API oficial?"}' \
  http://127.0.0.1:8000/web/chat
```

### O que verificar nos logs

- `X-Request-ID` presente em todas as respostas
- Evento `chat_completed` com `request_id`, `domain`, `confidence`, `escalated`,
  `handoff_reasons`, `retrieval_backend`, `references_count`, `error_code`
- `error_code` nulo quando provider e banco estiverem configurados
- Nenhum log com secret, IP real, PII ou payload bruto

### Criterios de sucesso

- `/health` responde `200` com `X-Request-ID`
- `/health/ready` responde `200` com banco, migrations, retrieval e outbox
  saudaveis
- `/domains` lista `suporte-vps-whatsapp`
- `/ingestion/suporte-vps-whatsapp/preview` retorna `document_count >= 1`
- `/chat` responde com `error_code: null` quando provider e banco estiverem ok
- Fallback seguro com `error_code: provider_error` quando provider ausente
- feedback confirma `storage=postgres` depois do commit
- handoff enfileirado retorna `handoff_status=handoff_queued`

---

## 11. Checklist antes de expor publicamente

- [ ] `API_SECRET_KEY` definido com valor forte e unico
- [ ] `DATABASE_URL` apontando para o novo PostgreSQL
- [ ] Snapshot e preflight concluidos
- [ ] Migrations `001-008` verificadas pelo runner
- [ ] `/health/ready` aprovado com banco, migrations, retrieval e outbox
- [ ] Dominio ingerido no pgvector
- [ ] `/health`, `/domains`, `/chat` respondendo no loopback
- [ ] HTTPS ativo antes de abrir para fora
- [ ] Porta `5432` fechada para a internet
- [ ] `.env` fora do Git com permissao restrita
- [ ] Cada secret unico, sem reutilizacao entre variaveis
- [ ] `ENABLE_CHAT_UI=false`
- [ ] `ENABLE_PUBLIC_CHAT_UI=true`
- [ ] `WEB_CHAT_COOKIE_SECURE=true`
- [ ] `WEB_CHAT_RATE_LIMIT_PER_MINUTE=10`
- [ ] `WEB_CHAT_SESSION_COOKIE=sfaq_web_session_staging`
- [ ] Credenciais de staging separadas das de producao

---

## Sinais de bloqueio

Parar e registrar bloqueio privado se ocorrer:

- Python < 3.11 no servidor
- Falha de instalacao de dependencia
- API nao sobe
- Dominio nao carrega
- Migrations falham por extensao `vector` ou `pgcrypto` ausente
- Provider falha sem `provider_error` rastreavel
- Cookie publico saindo sem `Secure` em staging
- Log vazando secret, IP, PII ou payload bruto
- Necessidade de abrir firewall publico para continuar a validacao

---

## Referencias

- [Mapa oficial de ambientes](../environments.md)
- [Runbook de runtime controlado](vps-controlled-runtime.md)
- [Smoke HTTP automatizado](staging-http-smoke.md)
- [Web chat V0 HostGator staging](hostgator-staging-web-chat-v0.md)
- [Plano de seguranca da VPS](../security/vps-security-plan.md)
- [Relatorio historico de validacao anterior](../archive/historical-reports/staging-runtime-validation-report.md)
- [Plano V1B WhatsApp OTP (arquivado)](../archive/implementation-plans/web-chat-v1b-postgres-n8n-plan.md)
- [Checklist de promocao da Fase 0](phase0-staging-promotion-evidence.md)
