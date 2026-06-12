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
- ingress interno HMAC com idempotencia persistente antes do n8n;
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

O rollout de privacidade de conversas usa expand/contract. Em banco existente,
nunca tente aplicar `006` e `007` como uma unica etapa:

```powershell
python -m scripts.migrate apply --target 006_conversations_messages.sql
# publicar e validar o writer novo, ainda compativel com a fase expandida
python -m scripts.backfill_conversation_privacy
python -m scripts.backfill_conversation_privacy --verify-contract-ready
python -m scripts.migrate apply
python -m scripts.migrate verify
```

O backfill transforma `session_id` em HMAC, sanitiza mensagens e consolida
conversas ativas duplicadas antes da `007` remover o identificador bruto e
criar a unicidade por dominio, canal e hash. O mesmo
`PERSISTENCE_HASH_SECRET` e `PERSISTENCE_HASH_VERSION` deve ser preservado em
todas as rodadas. `--verify-contract-ready` somente pode ser executado depois
de confirmar que nenhum writer legado continua ativo.

Em banco novo, a fase contract tambem exige confirmacao explicita. Isso evita
que um banco vazio remova `session_id` enquanto uma versao antiga da aplicacao
ainda pode escrever.

Retencao deve ser inspecionada antes da exclusao:

```powershell
python -m scripts.prune_operational_data --dry-run
python -m scripts.prune_operational_data --batch-size 1000
```

O job usa lotes limitados e transacoes separadas. Ele nunca remove eventos
`pending`, `retryable_failed` ou `dead_letter`; somente eventos
`delivered` e receipts entregues ultrapassando o horizonte configurado sao
elegiveis para limpeza. O horizonte define tambem por quanto tempo a
idempotencia historica desses eventos permanece consultavel.
Feedback expirado e removido antes de auditorias; uma auditoria referenciada
por feedback ainda retido nunca e apagada.

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
- repetir os gates SQL e concorrencia no PostgreSQL de staging depois do
  snapshot; a prova local real ja passou com `20 passed`;
- reingerir o dominio e revalidar os quatro casos recalibrados da gate.
- confirmar em smoke privado se a Evolution ou o proxy final honra
  `X-Idempotency-Key`; sem isso, timeout incerto continua exigindo
  reconciliacao manual por causa da semantica at-least-once.

O saneamento offline desses casos esta registrado em
`docs/quality-plans/pgvector-gate-backlog-2026-06-11.md`.
As evidencias e bloqueios do host local estao registrados em
`docs/runbooks/local-phase0-validation-report-2026-06-12.md`.

Enquanto essas evidencias nao existirem, a Fase 0 esta implementada no
repositorio, mas nao validada operacionalmente.
