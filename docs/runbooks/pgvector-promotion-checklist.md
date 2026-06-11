# Runbook - Checklist de promocao do pgvector

## Objetivo

Definir criterios objetivos para decidir quando `RETRIEVAL_BACKEND=pgvector`
pode deixar de ser feature flag validada e virar padrao do runtime.

Este checklist nao altera ambiente, schema, migrations, indices ou workflows.

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

- a `pgvector_gate.yaml` em staging ficar proxima do baseline local `74/78`
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

Para cada rodada de decisao, registrar:

- branch e commit
- backend usado
- total de casos
- aprovados/reprovados
- quantidade media de referencias
- principais falhas por tipo: `conteudo`, `retrieval`, `confidence`,
  `handoff`, `provider`, `contrato`
- recomendacao: promover, manter feature flag, melhorar conteudo ou ajustar
  handoff/confidence

## Fronteiras de ownership

- Renan coordena criterios, evals, contratos, schema, migrations, indices,
  persistencia e qualidade.
- Juliano responde pelo runtime oficial, rede, proxy, TLS e logs de operacao.
- n8n deve consumir o contrato HTTP, nao redesenhar inteligencia do backend.
