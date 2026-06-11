# Fase 0 - Reducao de Risco Operacional

## Objetivo

Criar os trilhos de confiabilidade antes da persistencia completa, WhatsApp
real e promocao operacional. Esta fase evita promessa falsa de handoff,
migration manual sem rastreio e persistencia de dados sensiveis.

## Ownership Atual

- Renan: aplicacao, arquitetura, PostgreSQL, migrations, persistencia,
  contratos, seguranca, testes e integracao final.
- Juliano: VPS, Docker, rede, n8n, Evolution API, snapshots, alertas e
  recuperacao.
- Trabalho conjunto: migration em staging, teste de concorrencia, restore e
  aprovacao dos gates.

Este ownership substitui as atribuicoes operacionais antigas a Alexandre e
Silotto. Creditos historicos e autoria de migrations antigas permanecem.

## Entregas Implementadas No Repositorio

- runner forward-only `python -m scripts.migrate`;
- ledger `schema_migrations`, checksum e advisory lock;
- migration corretiva do estado OTP `exhausted`;
- migration de auditoria de chat, feedback confiavel e outbox;
- pool PostgreSQL compartilhado baseado em `psycopg_pool`;
- sanitizacao versionada antes da persistencia;
- outbox at-least-once com idempotency key e dispatcher separado;
- assinatura HMAC obrigatoria para entregas do dispatcher;
- `handoff_status` no contrato interno `/chat`;
- feedback PostgreSQL enriquecido pelo contexto confiavel do servidor;
- rede Docker privada compartilhada e limites de logs para n8n.

## Comandos

```powershell
python -m scripts.migrate status
python -m scripts.migrate baseline
python -m scripts.migrate apply
python -m scripts.migrate verify
python -m scripts.staging_phase0_preflight --snapshot-confirmed
python -m scripts.dispatch_outbox --once
python -m scripts.prune_operational_data
```

Use `baseline` somente quando `001` e `002` ja tiverem sido aplicadas
manualmente. Nunca altere uma migration aplicada; crie uma nova correcao
forward-only.

## Gates

- pgvector normal: `>=74/78`;
- `70-73`: exige relatorio e aprovacao conjunta;
- `<70`: bloqueia promocao;
- banco novo e banco com baseline devem aplicar migrations;
- quinta tentativa OTP deve terminar em `exhausted`;
- payload persistido e outbox nao podem conter PII ou secrets;
- handoff nao enfileirado deve informar indisponibilidade;
- restore deve medir `RPO <= 24h` e `RTO <= 4h`.

## Pendencias Externas

- criar e testar snapshots no provedor;
- executar restore cronometrado em ambiente isolado;
- configurar alertas reais de disco;
- criar a rede `supportfaq_internal` no runtime;
- configurar URLs privadas consumidas pelo dispatcher;
- executar gates SQL e concorrencia contra PostgreSQL real.

Enquanto essas evidencias nao existirem, a Fase 0 esta implementada no
repositorio, mas nao validada operacionalmente.
