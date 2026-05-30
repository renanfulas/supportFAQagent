# Runbook - Execucao da gate pgvector em staging

## Objetivo

Executar a suite `evals/pgvector_gate.yaml` em staging privado usando
`RETRIEVAL_BACKEND=pgvector`, provider real e conhecimento ja ingerido no
PostgreSQL.

Este runbook existe para responder uma pergunta operacional simples:

- o comportamento do staging ficou proximo do baseline validado no laboratorio
  local?

Se a resposta for sim, a gate pode ser tratada como estavel para o MVP. A
suite `curated` fica como backlog de calibracao, nao como bloqueio de avanco.

## Pre-requisitos

- staging privado atualizado na `main`
- `.env` privado fora do Git
- `DATABASE_URL` configurado para o PostgreSQL com pgvector
- `OPENAI_API_KEY` ou provider equivalente configurado
- `API_SECRET_KEY` configurado fora de ambiente local
- conhecimento do dominio ingerido com `scripts/ingest_domain_pgvector.py`
- arquivo `domains/suporte-vps-whatsapp/evals/pgvector_gate.yaml` presente

## Baseline local

No laboratorio local, a gate validada ficou em:

- `74/78` aprovados
- `4` falhas restantes tratadas como backlog de calibracao:
  - `vps-020-erro-permission-denied-publickey`
  - `vps-049-disco-cheio`
  - `vps-051-site-lento`
  - `vps-091-banco-consome-disco`

Use esse baseline como referencia, nao como garantia numerica absoluta. O
importante e a proximidade do comportamento e a ausencia de falhas novas de
provider, banco, references ou handoff critico.

## Pre-check

No runtime de staging, confirme que o ambiente esta apontando para pgvector:

```bash
python -c "from app.core.config import get_settings; s=get_settings(); print('env=', s.app_env, 'backend=', s.retrieval_backend, 'db=', bool(s.database_url), 'openai=', bool(s.openai_api_key))"
```

Esperado:

- `backend= pgvector`
- `db= True`
- `openai= True`

## Atualizacao da ingestao

Reingira o dominio antes do eval para evitar drift entre conteudo e vetor:

```bash
python scripts/ingest_domain_pgvector.py --domain suporte-vps-whatsapp
```

Em staging privado, esse comando deve rodar no mesmo runtime ou rede onde o
hostname do PostgreSQL resolve.

## Execucao da gate

Rode a suite de gate:

```bash
python -m app.evals.run_domain_eval suporte-vps-whatsapp --file evals/pgvector_gate.yaml
```

## Criterio de decisao

### Gate estavel para MVP

Pode considerar a gate estavel quando:

- o resultado ficar proximo do baseline local
- nao surgirem falhas novas de provider, banco ou contrato
- casos sensiveis continuarem escalando
- `references` continuarem no formato `list[str]`

Regra pratica:

- `>= 70/78`: gate aceitavel para MVP
- `64-69/78`: aceitavel com revisao curta das diferencas de ambiente
- `< 64/78`: investigar antes de tratar como estavel

### Nao promover sem revisar

Nao trate o staging como estavel se:

- houver `provider_error`, `retrieval_error` ou falha tecnica recorrente
- casos sensiveis deixarem de escalar
- aparecerem referencias incoerentes de forma sistematica
- o formato publico de resposta mudar

## Pos-gate

Se a gate ficar proxima do baseline local:

1. congele a `gate` como gate forte do MVP
2. trate os casos restantes como backlog de calibracao
3. use a `curated` para diagnostico mais amplo, nao como bloqueio

Rodada seguinte:

```bash
python -m app.evals.run_domain_eval suporte-vps-whatsapp --file evals/pgvector_curated.yaml
```

Prioridades de backlog da `curated`:

- referencias de `n8n`
- referencias de `vps-caiu.md`
- casos com `out_of_scope` indevido

## Relatorio sanitizado

Registrar somente:

- data
- branch e commit
- total de casos
- aprovados e reprovados
- principais falhas por tipo: `conteudo`, `retrieval`, `confidence`,
  `handoff`, `provider`, `contrato`
- comparacao curta com o baseline local
- recomendacao: aceitar gate do MVP, recalibrar threshold ou revisar conteudo

Nao registrar:

- `DATABASE_URL`
- API keys
- IPs internos ou publicos
- portas administrativas
- logs crus
- prompts completos
- payloads brutos
- respostas completas com risco de PII
