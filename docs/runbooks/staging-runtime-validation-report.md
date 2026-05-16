# Staging Runtime Validation Report

Data: 2026-05-16

## Status

Runtime de staging validado parcialmente no ambiente privado.

O backend foi sincronizado com a `main` atual, executado em loopback e validado
com smoke tests. Depois, o provider real foi configurado via `.env` privado e o
`POST /chat` foi revalidado sem cair no fallback `provider_error`.

Este relatorio e propositalmente sanitizado: nao inclui IP, hostname, usuario,
porta administrativa, credenciais, logs brutos, prompts completos ou valores de
segredo.

## Ambiente Validado

- Branch: `main`
- Commit: `5a5ade6`
- Python do virtualenv: `3.11.13`
- Bind usado durante os testes: `127.0.0.1:8000`
- Repositorio no servidor: copia unica confirmada
- `.env` privado: presente, fora do Git, com permissao restrita
- `OPENAI_API_KEY`: presente no ambiente privado
- `PROJECT_LLM_API_KEY_ALIAS`: presente no ambiente privado
- `DATABASE_URL`: ausente no momento da validacao

## Validacoes Executadas

- `pip install -e .[dev]`: ok
- `python -m compileall app tests scripts`: ok
- `python -m pytest`: `108 passed`
- `python -m app.evals.run_domain_eval suporte-vps-whatsapp`: ok

## Smoke Tests

- `GET /health`: ok, com `X-Request-ID`
- `GET /domains`: ok, dominio `suporte-vps-whatsapp` carregado
- `GET /ingestion/suporte-vps-whatsapp/preview`: ok, 8 documentos e 12 chunks
- `POST /chat` sem provider configurado: ok, fallback seguro com `provider_error`
- `POST /chat` com provider real configurado: ok, `error_code=null`

## Observabilidade

- `http_request`: presente nos logs da execucao controlada
- `chat_completed`: presente nos logs da execucao controlada
- `request_id` enviado pelo cliente: preservado no `/chat`
- `provider_error`: rastreavel quando a chave do provider estava ausente
- provider real: validado sem `provider_error` apos configurar chave privada

## Higiene Operacional

- A API temporaria foi parada apos os smoke tests.
- A porta de teste ficou fechada ao final da validacao.
- Nenhum segredo foi versionado.
- O relatorio privado completo ficou apenas no servidor.

## Bloqueios Pendentes

- `DATABASE_URL` ainda precisa ser configurado no ambiente privado.
- As validacoes SQL/pgvector ainda precisam ser executadas com `psql`.
- A credencial de provider deve ser rotacionada depois da validacao operacional,
  pois foi compartilhada fora do cofre de secrets.
- A credencial SSH/root usada na contingencia tambem deve ser rotacionada.

## Proximo Passo Seguro

Configurar `DATABASE_URL` privado e executar, em sessao privada, as validacoes:

```bash
psql "$DATABASE_URL" -f migrations/001_initial_schema.sql
psql "$DATABASE_URL" -f tests/db/test_01_extensions.sql
psql "$DATABASE_URL" -f tests/db/test_02_schema.sql
psql "$DATABASE_URL" -f tests/db/test_03_idempotency.sql
psql "$DATABASE_URL" -f tests/db/test_04_vector_search.sql
psql "$DATABASE_URL" -f tests/db/test_05_isolation.sql
psql "$DATABASE_URL" -f tests/db/validate_pgvector_search.sql
```

Publicar somente o resultado sanitizado, sem output bruto com dados de ambiente.
