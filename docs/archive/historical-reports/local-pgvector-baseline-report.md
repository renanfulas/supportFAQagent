# Local pgvector Baseline Report

Data: 2026-05-30

## Status

Baseline local consolidado para comparacao com staging privado.

O ambiente local foi preparado com:

- `RETRIEVAL_BACKEND=pgvector`
- PostgreSQL local descartavel com pgvector
- ingestao do dominio `suporte-vps-whatsapp`
- provider real configurado para embeddings e resposta

Este relatorio e sanitizado. Nao inclui `DATABASE_URL`, API keys, IPs, portas
administrativas ou logs brutos.

## Ambiente Local

- Branch: `main`
- Commit de referencia do baseline: `4bee1bd`
- `APP_ENV`: `development`
- `RETRIEVAL_BACKEND`: `pgvector`
- `DATABASE_URL`: presente
- `OPENAI_API_KEY`: presente

Pre-check executado:

```bash
python -c "from app.core.config import get_settings; s=get_settings(); print('env=', s.app_env, 'backend=', s.retrieval_backend, 'db=', bool(s.database_url), 'openai=', bool(s.openai_api_key))"
```

Resultado esperado e observado:

- `env= development`
- `backend= pgvector`
- `db= True`
- `openai= True`

## Validacoes Executadas

- `python -m pytest tests/test_handoff_service.py tests/test_chat_flow_errors.py`
- `python -m compileall app tests scripts`
- `python scripts/ingest_domain_pgvector.py --domain suporte-vps-whatsapp`
- `python -m app.evals.run_domain_eval suporte-vps-whatsapp --file evals/pgvector_gate.yaml`
- `python -m app.evals.run_domain_eval suporte-vps-whatsapp --file evals/pgvector_curated.yaml`

## Ingestao

Ultima ingestao local observada:

- `11` documentos
- `21` chunks
- `21` embeddings persistidos

## Gate

Suite:

- `domains/suporte-vps-whatsapp/evals/pgvector_gate.yaml`

Resultado local:

- `74/78` aprovados
- `4` falhas

Casos restantes:

- `vps-020-erro-permission-denied-publickey`
- `vps-049-disco-cheio`
- `vps-051-site-lento`
- `vps-091-banco-consome-disco`

Leitura operacional:

- gate forte para MVP
- falhas restantes tratadas como backlog de calibracao, nao bloqueio

## Curated

Suite:

- `domains/suporte-vps-whatsapp/evals/pgvector_curated.yaml`

Resultado local:

- `179/240` aprovados
- `61` falhas

Principais grupos:

- referencias de `n8n`
- referencias de `vps-caiu.md`
- casos com `out_of_scope` indevido
- alguns limiares de `low_confidence`

Leitura operacional:

- diagnostico amplo valido
- nao usar como bloqueio de release do MVP

## Recomendacao

Usar este baseline como referencia oficial para a rodada de staging descrita em
`docs/runbooks/staging-pgvector-gate.md`.

Critico para a comparacao:

- o staging deve ficar proximo de `74/78` na gate
- nao devem surgir falhas novas de provider, retrieval ou contrato
- a `curated` deve continuar como backlog de calibracao

## Proximo Passo

No staging privado:

1. reingirir o dominio
2. rodar `pgvector_gate.yaml`
3. comparar com este baseline local
4. se o resultado ficar proximo, aceitar a gate como estavel para o MVP
