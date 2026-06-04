# Configuracao da VPS - supportFAQagent

Guia de instalacao e configuracao do ambiente de staging na nova VPS.
Baseado em `docs/environments.md`, `docs/runbooks/vps-controlled-runtime.md`,
`docs/runbooks/hostgator-staging-web-chat-v0.md` e
`docs/security/vps-security-plan.md`.

Ownership de VPS, deploy e runtime: Silotto.
Ownership de banco, migrations e pgvector: Alexandre.
Ownership de contratos, backend e testes: Renan.

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
N8N_OTP_DELIVERY_WEBHOOK_URL=<url-interna-do-webhook-n8n>
N8N_OTP_WEBHOOK_SECRET=<secret-dedicado-nao-reutilizar>

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

Aplicar em ordem. Nao pular nenhuma.

```bash
# Schema principal: dominios, artigos, chunks, embeddings, conversas, mensagens
psql "$DATABASE_URL" -f migrations/001_initial_schema.sql

# Web auth OTP V1B: verified_identities, web_sessions, otp_challenges
psql "$DATABASE_URL" -f migrations/002_web_auth.sql
```

Validar com os testes SQL do repositorio:

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

# Dominios carregados
curl -i http://127.0.0.1:8000/domains

# Preview de ingestao
curl -i http://127.0.0.1:8000/ingestion/suporte-vps-whatsapp/preview

# Chat
curl -i \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: smoke-001" \
  -d '{"domain":"suporte-vps-whatsapp","session_id":"smoke","message":"Como instalar a Evolution API na VPS?"}' \
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
  -d '{"message":"Como conectar o WhatsApp na Evolution API?"}' \
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
- `/domains` lista `suporte-vps-whatsapp`
- `/ingestion/suporte-vps-whatsapp/preview` retorna `document_count >= 1`
- `/chat` responde com `error_code: null` quando provider e banco estiverem ok
- Fallback seguro com `error_code: provider_error` quando provider ausente

---

## 11. Checklist antes de expor publicamente

- [ ] `API_SECRET_KEY` definido com valor forte e unico
- [ ] `DATABASE_URL` apontando para o novo PostgreSQL
- [ ] Migrations `001` e `002` aplicadas e testes SQL passando
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
- [Relatorio de validacao anterior](staging-runtime-validation-report.md)
- [Plano V1B WhatsApp OTP](../quality-plans/web-chat-v1b-postgres-n8n-plan.md)
