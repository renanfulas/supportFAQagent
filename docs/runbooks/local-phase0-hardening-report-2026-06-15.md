# Relatorio Local Dos Hardenings Da Fase 0 - 2026-06-15

## Decisao

Os quatro hardenings locais bloqueantes foram implementados e validados.

A Fase 0 continua `not_approved` para staging porque snapshot, restore, rede
privada, alertas e integracoes externas ainda exigem evidencia do ambiente
oficial.

## Hardenings Fechados

- testes PostgreSQL opt-in recusam execucao sem
  `PHASE0_TEST_DATABASE_DISPOSABLE=true` e nome de banco explicitamente
  descartavel;
- readiness falha fechado fora de ambientes de desenvolvimento quando
  PostgreSQL esta desabilitado;
- `migrate verify` e readiness detectam drift de colunas, indices, triggers e
  constraints criticas da Fase 0;
- CI PostgreSQL executa readiness real com persistencia, web auth e ingress
  habilitados.
- suite de testes usa defaults deterministas e nao herda provider real ou
  retrieval privado do `.env` local por acidente.

## Evidencias Locais

- rollout completo `001-008` em PostgreSQL/pgvector descartavel;
- segunda aplicacao idempotente;
- `migrate verify`: `8 applied migration(s)`;
- readiness real: banco, migrations, retrieval lexical e outbox `ok`;
- restart do PostgreSQL preservou migrations e readiness;
- testes PostgreSQL opt-in: `20 passed`;
- contratos da Fase 0: `166 passed`;
- testes focados dos hardenings: `55 passed`;
- suite completa deterministica com PostgreSQL real: `356 passed`;
- `compileall`, `pip check`, YAML dos workflows e `git diff --check` verdes;
- tentativa sem marcador descartavel foi recusada antes da coleta dos testes.

## Bloqueio De Staging

Em 15/06/2026, a conexao SSH com o staging oficial na porta privada expirou
por timeout. Nenhuma migration, snapshot ou alteracao de infraestrutura foi
executada no ambiente oficial.

Continuam bloqueantes:

- snapshot concluido no provedor;
- preflight com `ready_for_migration_review: true`;
- rollout e concorrencia no PostgreSQL de staging;
- rede privada entre API, n8n e Evolution;
- handoff, retry, `dead_letter` e idempotencia externa;
- restart completo do stack;
- alertas reais de disco;
- restore isolado cronometrado;
- gate pgvector final apos o rollout.
