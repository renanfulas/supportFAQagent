# Runbook - Snapshot E Restore Da Fase 0

## Meta

- RPO maximo: 24 horas.
- RTO maximo: 4 horas.
- Estrategia aceita: snapshots do provedor, sem copia externa.

Essa estrategia e suficiente para staging operacional, mas nao caracteriza
producao resiliente.

## Antes De Migration Ou Infraestrutura

1. Confirmar uso de disco abaixo do limite critico.
2. Registrar branch, commit e migrations pendentes.
3. Criar snapshot privado no provedor.
4. Confirmar que o snapshot aparece como concluido.
5. Executar o preflight somente leitura:

```bash
python -m scripts.staging_phase0_preflight \
  --snapshot-confirmed \
  --env-file .env \
  --output /tmp/supportfaq-phase0-preflight.md
```

6. Revisar `ready_for_migration_review: true`.
7. Executar `python -m scripts.migrate status` novamente na mesma sessao.
8. Se `006` e `007` estiverem pendentes, aplicar somente a fase expand:

```bash
python -m scripts.migrate apply --target 006_conversations_messages.sql
```

9. Publicar e validar o writer novo, ainda compativel com a fase expandida.
10. Executar o backfill ate zerar pendencias:

```bash
python -m scripts.backfill_conversation_privacy
```

11. Confirmar que writers legados foram drenados e marcar o contrato pronto:

```bash
python -m scripts.backfill_conversation_privacy --verify-contract-ready
```

12. Somente depois executar `python -m scripts.migrate apply` e
    `python -m scripts.migrate verify`.

Para migrations que nao atravessam o contrato `006`/`007`, o operador pode
aplicar normalmente depois do snapshot, preflight e revisao do `status`.

O preflight nunca executa `baseline`, `apply`, backfill, restore ou limpeza
Docker. A flag
`--snapshot-confirmed` registra apenas a confirmacao operacional; ela nao cria
o snapshot no provedor. O arquivo privado indicado por `--env-file` e carregado
somente para validar presenca e executar `migrate status`; valores nunca entram
no relatorio.

Nunca publicar nome do snapshot, IP, hostname, usuario ou credencial.

## Relatorio De Decisao

Depois de cada rodada, gere um resumo sanitizado:

```bash
python -m scripts.phase0_operational_report \
  --snapshot passed \
  --preflight passed \
  --migrations passed \
  --postgres-concurrency passed \
  --restore blocked \
  --pgvector-gate pending \
  --output /tmp/supportfaq-phase0-decision.md
```

O resultado somente fica `decision: approved` quando todos os gates estiverem
como `passed`.

## Restore Cronometrado

1. Registrar `snapshot_timestamp` e confirmar que a restauracao sera em VPS
   isolada, sem DNS publico apontando para ela.
2. Registrar `restore_started_at`.
3. Restaurar o snapshot em ambiente isolado.
4. Confirmar filesystem, containers e capacidade com:

```bash
python -m scripts.check_runtime_capacity --path / --warning 75 --critical 85 --min-free-gb 2
```

5. Executar `python -m scripts.migrate verify`.
6. Validar PostgreSQL, API, pgvector, outbox e volumes do agente.
7. Executar smoke HTTP sanitizado.
8. Confirmar eventos pendentes da outbox.
9. Registrar `restore_finished_at` e calcular RTO.
10. Comparar o dado mais recente restaurado com o horario do snapshot para
   medir RPO.

O relatorio deve confirmar explicitamente que o host validado e uma VPS
restaurada isolada, nao o staging oficial.

## Run-Sheet Do Host Restaurado

Execute na VPS restaurada isolada, na ordem. Todos os comandos abaixo sao
somente leitura: nenhum cria snapshot, restaura ou apaga dado. Anote
`restore_started_at` antes do passo 1 e `restore_finished_at` depois do passo 5
(ISO-8601 UTC, ex.: `2026-07-01T03:10:00Z`).

```bash
# 1. capacidade do filesystem
python -m scripts.check_runtime_capacity --path / --warning 75 --critical 85 --min-free-gb 2

# 2. migrations integras e sem drift
python -m scripts.migrate verify

# 3. readiness (banco, migrations, retrieval, outbox)
python -m scripts.check_readiness

# 4. smoke HTTP sanitizado (base URL privada do host restaurado)
python -m scripts.staging_smoke --base-url http://127.0.0.1:8000

# 5. pgvector, outbox e volumes: confirmar manualmente (chunks respondem,
#    eventos pendentes drenam, volumes PostgreSQL presentes).
```

Depois agregue a evidencia. O helper e somente leitura: calcula RTO/RPO, aplica
`RTO <= 4h` / `RPO <= 24h` e imprime o veredito `restore`. Troque cada status
pelo resultado real e informe os quatro timestamps:

```bash
python -m scripts.phase0_restore_validate \
  --snapshot-timestamp <ISO> \
  --restore-started-at <ISO> \
  --restore-finished-at <ISO> \
  --latest-data-timestamp <ISO> \
  --capacity passed --migrate-verify passed --readiness passed \
  --pgvector passed --outbox passed --volumes passed --smoke passed \
  --output /tmp/supportfaq-phase0-restore.md
```

Alimente o veredito no relatorio de decisao:

```bash
python -m scripts.phase0_operational_report \
  --snapshot passed --preflight passed --migrations passed \
  --postgres-concurrency passed --pgvector-gate passed \
  --restore <veredito-do-helper> \
  --output /tmp/supportfaq-phase0-decision.md
```

Tabela de evidencia (preencher e anexar sanitizado ao PR):

| Campo | Valor |
| --- | --- |
| snapshot_timestamp | |
| restore_started_at | |
| restore_finished_at | |
| RTO (h) / RPO (h) | |
| capacity / migrate_verify / readiness | |
| pgvector / outbox / volumes / smoke | |
| restore verdict | |

Nunca inclua nome de snapshot, IP, hostname, usuario ou credencial na evidencia.

## Criterio

- aprovado: RPO ate 24 horas e RTO ate 4 horas;
- reprovado: restore incompleto, dados inconsistentes ou tempo acima da meta;
- bloqueio: necessidade de expor segredo ou operar no ambiente oficial sem
  snapshot concluido.

## Risco Aceito

Snapshots podem capturar escrita em andamento e dependem do mesmo provedor da
VPS. Um backup logico externo deve ser adicionado antes de classificar o
ambiente como producao resiliente.
