# Relatorio Local Da Fase 0 - 2026-06-12

## Decisao

`not_approved`

A implementacao, os contratos locais e a prova PostgreSQL/pgvector real estao
verdes. A Fase 0 ainda depende de snapshot, restore e smokes privados.

## Evidencias Verdes

- suite completa com PostgreSQL/pgvector real: `348 passed`, sem skips;
- migrations `001` a `008` aplicadas e verificadas;
- `20 passed` nos testes PostgreSQL opt-in de concorrencia, upgrade e feedback;
- repeticao em banco descartavel novo confirmou o bloqueio seguro da migration
  `007` antes do backfill e terminou novamente com `348 passed`;
- `/health/ready` real retornou `200` com banco, migrations, retrieval lexical
  e outbox saudaveis;
- restart do PostgreSQL preservou o schema e `migrate verify` continuou verde;
- `python -m compileall -q app scripts tests`;
- `python -m pip check`;
- `git diff --check`;
- JSON dos workflows n8n e YAML de CI/Compose parseados;
- `docker compose config --quiet` validou o Compose n8n sem subir containers;
- `psycopg-pool` instalado no ambiente virtual local.

## Riscos Fechados Nesta Rodada

- checksum de migration portavel entre LF e CRLF no runner e readiness;
- ledger e readiness ligados ao schema atual;
- fechamento de pool quando a inicializacao falha;
- timeout de conexao e query no dispatcher;
- HMAC de observabilidade sem fallback enumeravel;
- validacao de `request_id` tambem dentro do repository de chat;
- janela de reclaim compartilhada entre dispatcher e readiness;
- banco do n8n isolado da rede compartilhada com a API;
- payload bruto de execucoes n8n nao persistido em sucesso ou erro;
- chave idempotente propagada ate as chamadas da Evolution;
- workflow de entrada nao duplica a notificacao autoritativa da outbox.

## Runtime Local Usado

- Ubuntu em WSL1, sem exigir virtualizacao de hardware;
- PostgreSQL 18;
- pgvector `0.8.1`;
- banco descartavel isolado na porta local `55432`.

Quando a role da aplicacao nao e superusuaria, `vector` e `pgcrypto` precisam
ser provisionadas previamente por uma role administrativa. A role comum
executou o restante do rollout e dos testes.

Nenhum banco privado ou de staging foi alterado durante essa validacao.

## Pendencias Externas

Staging ainda deve provar snapshot, restore cronometrado, rede privada,
smoke n8n/Evolution, alertas reais e persistencia apos restart do stack.

A matriz bloqueante e a sequencia operacional estao em
`docs/runbooks/phase0-staging-promotion-evidence.md`.
