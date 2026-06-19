# Runbook - Checklist de promocao do pgvector

## Objetivo

Definir criterios objetivos para decidir quando `RETRIEVAL_BACKEND=pgvector`
pode deixar de ser feature flag validada e virar padrao do runtime de staging.

Este checklist nao altera ambiente, schema, migrations, indices ou workflows.

## Decisao Atual

Em 19/06/2026, `RETRIEVAL_BACKEND=pgvector` foi promovido como default
operacional do staging. O codigo continua preservando `lexical` como default
seguro para local/CI e rollback operacional.

Evidencia usada na decisao:

- staging em `main`, commit `61ea039`;
- `.env` privado com `RETRIEVAL_BACKEND=pgvector`;
- `DATABASE_URL` e provider de embeddings presentes;
- `scripts.check_readiness` com database, migrations, retrieval `pgvector` e
  outbox `ok`;
- `pgvector_gate.yaml` em staging com `76/78`, acima do criterio normal
  `>=74/78`;
- smoke HTTP privado com `/health`, `/domains` e `/chat` passando;
- rollback documentado para `RETRIEVAL_BACKEND=lexical`.

O restore cronometrado continua um gate separado de recuperacao operacional; ele
nao invalida a decisao de retrieval, mas ainda mantem a Fase 0 operacional como
`not_approved`.

## Pre-requisitos

- staging privado atualizado na `main`
- `DATABASE_URL` privado configurado
- provider de embeddings configurado
- conhecimento do dominio ingerido no pgvector
- seeds artificiais removidos
- baseline local da `pgvector_gate.yaml` consolidado
- execucao oficial da `pgvector_gate.yaml` em staging registrada
- `pgvector_curated.yaml` disponivel para diagnostico mais amplo
- relatorio sanitizado da execucao em staging

## Go / No-Go

### Go

Pode promover quando:

- a `pgvector_gate.yaml` em staging ficar no criterio normal `>=74/78`
- `/health`, `/domains` e `/chat` passam em staging
- casos saudaveis retornam `error_code=null`
- `references` continuam como `list[str]`
- referencias esperadas aparecem de forma consistente nos casos reais
- casos sensiveis continuam escalando
- `low_confidence` foi revisado caso a caso
- logs mostram `retrieval_backend=pgvector` e `references_count`
- nenhum log, relatorio ou eval contem PII, segredo ou identificador reversivel
- existe plano de rollback para `RETRIEVAL_BACKEND=lexical`

### No-Go

Nao promover se:

- houver erro tecnico recorrente de provider, embedding ou banco
- perguntas reais recuperarem referencias incoerentes
- casos sensiveis deixarem de escalar
- `references` mudarem de formato publico
- `session_id`, prompt, resposta completa, payload bruto ou segredo aparecerem
  em logs/relatorios
- o relatorio anonimo ainda nao tiver sido curado
- a operacao nao tiver como voltar rapidamente para lexical

## Rollback

Rollback esperado:

```bash
RETRIEVAL_BACKEND=lexical
```

Depois do rollback:

- rodar smoke `/health`, `/domains`, `/chat`
- preservar `request_id` e `error_code` dos casos que motivaram rollback
- registrar relatorio sanitizado
- nao apagar dados pgvector sem decisao explicita

## Evidencias minimas

Para cada rodada de decisao ou revalidacao, registrar:

- branch e commit
- backend usado
- total de casos
- aprovados/reprovados
- quantidade media de referencias
- principais falhas por tipo: `conteudo`, `retrieval`, `confidence`,
  `handoff`, `provider`, `contrato`
- recomendacao: manter pgvector no staging, acionar rollback lexical, melhorar
  conteudo ou ajustar handoff/confidence

## Fronteiras de ownership

- Renan coordena criterios, evals, contratos, schema, migrations, indices,
  persistencia e qualidade.
- Juliano responde pelo runtime oficial, rede, proxy, TLS e logs de operacao.
- n8n deve consumir o contrato HTTP, nao redesenhar inteligencia do backend.
