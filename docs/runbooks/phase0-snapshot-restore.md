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
  --n8n-smoke blocked \
  --restore blocked \
  --pgvector-gate pending \
  --output /tmp/supportfaq-phase0-decision.md
```

O resultado somente fica `decision: approved` quando todos os gates estiverem
como `passed`.

## Restore Cronometrado

1. Registrar horario inicial.
2. Restaurar o snapshot em ambiente isolado.
3. Confirmar filesystem e containers.
4. Executar `python -m scripts.migrate verify`.
5. Validar PostgreSQL, API, n8n e volumes.
6. Executar smoke HTTP sanitizado.
7. Confirmar eventos pendentes da outbox.
8. Registrar horario final e calcular RTO.
9. Comparar o dado mais recente restaurado com o horario do snapshot para
   medir RPO.

## Criterio

- aprovado: RPO ate 24 horas e RTO ate 4 horas;
- reprovado: restore incompleto, dados inconsistentes ou tempo acima da meta;
- bloqueio: necessidade de expor segredo ou operar no ambiente oficial sem
  snapshot concluido.

## Risco Aceito

Snapshots podem capturar escrita em andamento e dependem do mesmo provedor da
VPS. Um backup logico externo deve ser adicionado antes de classificar o
ambiente como producao resiliente.
