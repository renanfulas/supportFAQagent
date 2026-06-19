# Runbook - Execucao de eval pgvector real em staging

## Objetivo

Executar a futura suite `evals/pgvector_real.yaml` em staging privado usando
`RETRIEVAL_BACKEND=pgvector`, provider real e dados ja ingeridos no PostgreSQL.

Este runbook deve ser usado depois que o relatorio anonimo da HostGator for
convertido em evals curados.

## Pre-requisitos

- repositorio da VPS atualizado na `main`
- `.env` privado fora do Git
- `DATABASE_URL` configurado para o PostgreSQL com pgvector
- `OPENAI_API_KEY` ou provider equivalente configurado
- `API_SECRET_KEY` configurado fora de ambiente local
- dados do dominio ingeridos com `scripts/ingest_domain_pgvector.py`
- arquivo `domains/suporte-vps-whatsapp/evals/pgvector_real.yaml` criado a
  partir do template e sem PII

## Validacao previa

Confirme que o template foi substituido por casos reais anonimos:

```bash
test -f domains/suporte-vps-whatsapp/evals/pgvector_real.yaml
grep -q "substituir-por-pergunta-anonima-real" domains/suporte-vps-whatsapp/evals/pgvector_real.yaml && exit 1
```

Confirme que a ingestao atual tem dados:

```bash
python scripts/ingest_domain_pgvector.py --domain suporte-vps-whatsapp
```

Em staging privado, esse comando deve rodar dentro da rede onde o hostname do
PostgreSQL resolve, normalmente no mesmo runtime/container da aplicacao.

## Execucao do eval

No runtime de staging, carregue o `.env` privado e rode:

```bash
export RETRIEVAL_BACKEND=pgvector
python -m app.evals.run_domain_eval suporte-vps-whatsapp --file evals/pgvector_real.yaml
```

Se o host da VPS nao resolver o hostname interno do PostgreSQL, execute dentro
de um container temporario conectado a rede privada do servico. Nao registre
nomes de rede, hostnames internos, portas administrativas ou secrets no
relatorio publico.

## Smoke complementar

Antes ou depois do eval, rode um smoke HTTP do `/chat` com:

- `X-API-Key` privado
- `X-Request-ID` controlado
- pergunta anonima e curta
- `RETRIEVAL_BACKEND=pgvector`

Registrar somente:

- status HTTP
- `request_id`
- quantidade de `references`
- `confidence`
- `escalated`
- `handoff_reasons`
- `error_code`
- `retrieval_backend`

Nao registrar resposta completa se houver risco de PII.

## Relatorio sanitizado

Salvar um relatorio privado/sanitizado com:

- data
- branch e commit
- quantidade de casos
- quantidade aprovada/reprovada
- falhas agrupadas por tipo: `conteudo`, `retrieval`, `confidence`,
  `handoff`, `provider`, `contrato`
- recomendacao: manter pgvector no staging, acionar rollback lexical, melhorar
  conteudo ou ajustar threshold

Nao incluir:

- `DATABASE_URL`
- API keys
- IPs publicos ou privados
- usuarios
- portas administrativas
- logs crus
- prompts completos
- respostas completas com risco de PII
- headers, cookies, payloads brutos ou stack traces com detalhe de ambiente
- perguntas com identificadores reversiveis

## Criterio de decisao

So considerar promocao de `pgvector` para padrao permanente quando:

- casos saudaveis retornarem `error_code=null`
- referencias esperadas aparecerem de forma consistente
- casos sensiveis continuarem escalando
- `low_confidence` tiver sido revisado caso a caso
- falhas de conteudo tiverem backlog claro
