# Runbook - Smoke HTTP automatizado em staging

## Objetivo

Executar checks HTTP sanitizados depois de atualizar o runtime de staging para a
`main`, sem imprimir secrets, payload bruto, resposta completa ou PII.

Use este runbook para validar rapidamente:

- `/health`
- `/domains`
- `/ingestion/{domain}/preview` quando o operador precisar conferir a base local autenticada
- `/chat`
- `/feedback` opcional, apenas quando for seguro registrar feedback operacional

## Pre-requisitos

- API rodando no runtime alvo
- `.env` privado fora do Git
- `API_SECRET_KEY` carregado no shell ou passado de forma privada
- se o objetivo for validar pgvector, runtime com `RETRIEVAL_BACKEND=pgvector`
- se o objetivo for validar provider real, runtime com `OPENAI_API_KEY` privado

## Execucao recomendada

No ambiente privado:

```bash
export API_SECRET_KEY="<secret-privado>"
python scripts/staging_smoke.py \
  --base-url http://127.0.0.1:8000 \
  --domain suporte-vps-whatsapp \
  --request-id smoke-$(date +%Y%m%d%H%M%S) \
  --output /tmp/supportfaq-staging-smoke.md
```

Se o host da VPS estiver com Python antigo, execute o smoke dentro do container
da API ou em um ambiente Python 3.11+:

```bash
docker exec supportfaq_api python scripts/staging_smoke.py \
  --base-url http://127.0.0.1:8000 \
  --domain suporte-vps-whatsapp \
  --request-id smoke-$(date +%Y%m%d%H%M%S) \
  --output /tmp/supportfaq-staging-smoke.md
```

Motivo: o script usa recursos da versao moderna do Python e pode falhar no
Python do host mesmo quando a API esta saudavel.

Para tambem validar o contrato atual de feedback:

```bash
python scripts/staging_smoke.py \
  --base-url http://127.0.0.1:8000 \
  --domain suporte-vps-whatsapp \
  --feedback
```

## O que o relatorio registra

- data de execucao
- `base_url` usada
- `request_id`
- status HTTP de cada check
- latencia HTTP aproximada de cada check
- `confidence`
- `escalated`
- `handoff_reasons`
- quantidade de referencias
- `error_code`
- status do feedback, quando habilitado

## O que nao registrar

- `API_SECRET_KEY`
- `OPENAI_API_KEY`
- `DATABASE_URL`
- headers completos
- payload bruto
- `session_id` real
- pergunta real com identificador reversivel
- resposta completa do agente
- logs crus
- IPs, usuarios, portas administrativas ou hostnames internos

## Como correlacionar com logs

Use o mesmo `request_id` no relatorio e nos logs do backend.

O evento `chat_completed` deve conter:

- `request_id`
- `retrieval_backend`
- `references_count`
- `total_ms`
- `retrieval_ms`
- `llm_ms`
- `confidence`
- `escalated`
- `error_code`

Se `retrieval_ms` subir, investigue banco, embeddings ou rede interna.
Se `llm_ms` subir, investigue provider, timeout ou conectividade externa.
Se `error_code` vier preenchido, preserve o codigo no relatorio sanitizado e
nao publique resposta completa.
