# Runbook - VPS Controlled Runtime

Este runbook descreve como validar o runtime do `supportFAQagent` em uma VPS de forma controlada, sem expor IPs reais, hostnames, usuarios, portas administrativas, credenciais ou logs sensiveis no repositorio publico.

## Objetivo

Provar que a API FastAPI sobe na VPS, carrega o dominio inicial, le a base de conhecimento, chama o provider quando configurado e registra eventos rastreaveis com `request_id`.

## Status desta frente em 16/05/2026

Ja preparado no repositorio:

- runbook de execucao controlada
- hardening basico de runtime e seguranca de rotas
- `API_SECRET_KEY` obrigatoria fora de desenvolvimento
- `chat-ui` local/staging para testes controlados, quando liberada
- smoke tests automatizados no codigo
- preflight de runtime via PowerShell sem imprimir valores de segredo

Ainda nao comprovado neste runbook:

- execucao real em VPS privada do staging oficial
- resultado sanitizado dos smoke tests
- validacao privada de conectividade com `DATABASE_URL`

Evitar retrabalho:

- nao reabrir discussao sobre bind local, portas temporarias e sigilo de segredo sem evidencia nova
- nao mover este runbook para cobrir schema, migrations, indices ou tuning de `pgvector`
- nao misturar validacao operacional do staging com definicao de banco oficial ou SQL final

## Escopo

Incluido nesta etapa:

- validar runtime Python
- preparar diretorio de deploy
- configurar variaveis de ambiente locais
- instalar dependencias
- subir a API em bind local
- validar endpoints de smoke test
- verificar logs basicos
- registrar resultado sanitizado
- manter portas temporarias de debug fechadas para acesso publico

Fora do escopo desta etapa:

- PostgreSQL
- pgvector
- migrations
- persistencia real de conversas ou feedback
- n8n
- Cloudflare publico
- abertura ampla de firewall
- exposicao publica de portas temporarias como `8081`
- DNS definitivo

## Pre-requisitos

- Acesso SSH autorizado a VPS.
- Python `3.11+` disponivel.
- Git disponivel.
- Acesso de saida para instalar dependencias Python.
- Acesso de saida para o provider LLM, quando `OPENAI_API_KEY` estiver configurada.
- Branch `main` atualizada.
- Nenhum segredo real salvo em arquivo versionado.

## Variaveis de ambiente

Criar um arquivo `.env` local no servidor, fora do Git, usando apenas valores reais no ambiente privado.

```bash
APP_NAME=supportFAQagent
APP_ENV=staging
DEFAULT_DOMAIN=suporte-vps-whatsapp
DOMAINS_PATH=domains
OPENAI_API_KEY=<set-private-value>
ANTHROPIC_API_KEY=
API_SECRET_KEY=<set-private-value>
DATABASE_URL=<set-private-value-when-available>
```

Regras:

- nunca commitar `.env`
- nao colar valores reais em issue, PR ou documento publico
- se `OPENAI_API_KEY` nao estiver disponivel, validar fallback `provider_error`
- se `DATABASE_URL` nao estiver disponivel, registrar como pendencia de banco
  sem bloquear smoke tests sem persistencia
- manter credenciais de producao separadas das credenciais de desenvolvimento

## Preparacao do codigo

Use caminhos e usuarios reais apenas no ambiente privado.

```bash
cd <deploy-root>
git clone <repo-url> supportFAQagent
cd supportFAQagent
git checkout main
git pull --ff-only origin main
```

Criar ambiente Python:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Validar localmente no servidor:

```bash
python -m pytest
python -m compileall app tests
python -m app.evals.run_domain_eval suporte-vps-whatsapp
```

Em Windows ou PowerShell, usar o preflight seguro para conferir ferramentas e
variaveis sem imprimir valores de segredo:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\runtime_preflight.ps1
```

## Execucao controlada

Rodar a API escutando somente em loopback durante a validacao inicial.

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Nao usar `0.0.0.0` nesta primeira etapa sem aprovacao explicita.
Nao manter portas alternativas como `8081` abertas para internet. Se uma porta
temporaria for usada para debug, remover o listener e a regra de firewall assim
que a validacao terminar.

## Smoke tests

Em outra sessao SSH, executar:

```bash
curl -i http://127.0.0.1:8000/health
```

Esperado:

- status `200`
- corpo com `{"status":"ok"}`
- header `X-Request-ID`

```bash
curl -i http://127.0.0.1:8000/domains
```

Esperado:

- status `200`
- lista contendo `suporte-vps-whatsapp`
- header `X-Request-ID`

```bash
curl -i http://127.0.0.1:8000/ingestion/suporte-vps-whatsapp/preview
```

Esperado:

- status `200`
- `document_count` maior ou igual a `1`
- `chunk_count` maior ou igual a `document_count`
- `sample_chunks` preenchido

```bash
curl -i \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: runtime-smoke-001" \
  -d '{"domain":"suporte-vps-whatsapp","session_id":"runtime-smoke","message":"Como instalar a Evolution API na VPS?"}' \
  http://127.0.0.1:8000/chat
```

Esperado:

- status `200`
- `request_id` preservado ou gerado
- `domain` igual a `suporte-vps-whatsapp`
- `answer` nao vazio
- `references` preenchido quando houver contexto
- `error_code` nulo ou `provider_error`
- se `error_code` for `provider_error`, a resposta deve ser rastreavel e segura

## Observabilidade

Confirmar nos logs:

- evento `http_request`
- evento `chat_completed`
- `request_id`
- `domain`
- `confidence`
- `escalated`
- `handoff_reasons`
- `error_code`, quando houver

Nao registrar em documento publico:

- IP real
- hostname real
- usuario SSH
- valor de segredo
- conteudo completo de prompt
- telefone, email, token ou qualquer PII
- logs brutos com informacao sensivel

## Criterios de sucesso

- API sobe sem erro.
- `/health` responde.
- `/domains` responde.
- preview de ingestao le os arquivos do dominio.
- `/chat` responde com provider real ou fallback seguro.
- logs contem `request_id`.
- nenhum segredo fica versionado.
- nenhum detalhe operacional real e publicado.

## Criterios de parada

Parar a execucao e registrar bloqueio privado se ocorrer:

- falha de instalacao de dependencia
- falta de Python compativel
- app nao sobe
- dominio nao carrega
- knowledge nao e encontrada
- provider falha sem `provider_error` rastreavel
- log vaza segredo ou PII
- necessidade de abrir firewall publico para continuar

## Proximo passo apos sucesso

Depois do smoke test controlado, preparar uma proposta separada para:

- servico persistente com `systemd` ou container
- politica de reinicio
- logs operacionais
- bind e proxy interno
- decisao sobre exposicao controlada
- hardening minimo antes de qualquer acesso publico

Depois da execucao real deste runbook, registrar um relatorio curto com tres blocos:

- o que ja estava pronto no repositorio e foi confirmado no ambiente
- o que ainda ficou pendente por dependencia de ambiente ou banco
- o que nao deve ser retrabalhado porque ja estava coberto no codigo ou na documentacao

Se `DATABASE_URL` estiver disponivel, executar a validacao SQL em uma sessao
privada e registrar somente o resultado sanitizado:

```bash
psql "$DATABASE_URL" -f migrations/001_initial_schema.sql
psql "$DATABASE_URL" -f tests/db/test_01_extensions.sql
psql "$DATABASE_URL" -f tests/db/test_02_schema.sql
psql "$DATABASE_URL" -f tests/db/test_03_idempotency.sql
psql "$DATABASE_URL" -f tests/db/test_04_vector_search.sql
psql "$DATABASE_URL" -f tests/db/test_05_isolation.sql
psql "$DATABASE_URL" -f tests/db/validate_pgvector_search.sql
```

Nao publicar output bruto se ele contiver hostname, usuario, nome real de banco
ou qualquer detalhe operacional sensivel.
## Relatorio sanitizado

Modelo de resultado para compartilhar no time:

```md
## Status

Pronto | Parcial | Bloqueado

## Ambiente

- Branch: main
- Runtime Python: <major.minor>
- Bind usado: loopback
- Provider configurado: sim/nao

## Smoke tests

- GET /health: ok/falhou
- GET /domains: ok/falhou
- GET /ingestion/suporte-vps-whatsapp/preview: ok/falhou
- POST /chat: ok/falhou

## Observabilidade

- X-Request-ID: presente/ausente
- chat_completed: presente/ausente
- provider_error rastreavel: sim/nao/nao aplicavel

## Bloqueios

- <listar sem segredos>

## Proximo passo recomendado

- <acao curta>
```
