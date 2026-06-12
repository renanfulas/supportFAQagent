# Checklist De Evidencias Para Promocao Da Fase 0

## Objetivo

Impedir que a Fase 0 seja aprovada somente porque o deploy iniciou. Cada gate
abaixo exige evidencia sanitizada e verificavel do ambiente de staging.

O relatorio local comprova codigo, migrations e PostgreSQL real em laboratorio.
Ele nao substitui snapshot, restore, rede privada ou integracoes externas.

## Precondicoes

- branch e commit candidatos registrados;
- snapshot concluido no provedor;
- uso de disco abaixo do limite critico;
- extensoes `vector` e `pgcrypto` provisionadas por uma role administrativa;
- secrets carregados somente no runtime privado;
- janela operacional aprovada por Renan e Juliano.

## Matriz De Evidencias

| Gate | Acao | Evidencia minima | Bloqueia aprovacao |
| --- | --- | --- | --- |
| Snapshot | criar snapshot antes da mudanca | horario, status concluido e retencao confirmada | sim |
| Preflight | executar `scripts.staging_phase0_preflight` | relatorio sanitizado com `ready_for_migration_review: true` | sim |
| Migrations | executar `status`, rollout expand/contract e `verify` | migrations `001` a `008` verificadas e segunda aplicacao idempotente | sim |
| Concorrencia | executar testes PostgreSQL opt-in | OTP, outbox, idempotencia e feedback verdes | sim |
| Readiness | consultar `/health/ready` | banco, migrations, retrieval e outbox saudaveis | sim |
| Rede privada | testar API, n8n e Evolution por nomes internos | conexoes internas verdes e PostgreSQL sem exposicao publica | sim |
| Handoff | simular n8n indisponivel e entrega falha | chat continua disponivel, retry e `dead_letter` observaveis | sim |
| Idempotencia externa | repetir chamada com mesma chave | Evolution ou proxy nao produz segunda acao logica | sim |
| Restart | reiniciar stack completo | dados, migrations e outbox preservados | sim |
| Disco | configurar alertas | alertas de 75% e 85% comprovados | sim |
| Restore | restaurar snapshot isolado e cronometrar | `RPO <= 24h`, `RTO <= 4h` e servicos validados | sim |
| Pgvector | executar gate oficial | resultado `>=74/78`, ou aprovacao documentada para `70-73` | sim |

## Sequencia Operacional

1. Criar snapshot e registrar inicio da janela.
2. Executar preflight somente leitura.
3. Revisar `migrate status`.
4. Aplicar migrations conforme o runbook expand/contract.
5. Executar testes PostgreSQL opt-in e readiness.
6. Validar rede privada, handoff e idempotencia externa.
7. Reiniciar o stack e repetir readiness.
8. Executar a gate pgvector.
9. Restaurar o snapshot em ambiente isolado e medir RPO/RTO.
10. Gerar o relatorio de decisao sanitizado.

## Comandos De Aplicacao

Os valores de ambiente devem existir somente na sessao privada:

```bash
python -m scripts.staging_phase0_preflight \
  --snapshot-confirmed \
  --env-file .env \
  --output /tmp/supportfaq-phase0-preflight.md

python -m scripts.migrate status
python -m scripts.migrate apply --target 006_conversations_messages.sql
python -m scripts.backfill_conversation_privacy
python -m scripts.backfill_conversation_privacy --verify-contract-ready
python -m scripts.migrate apply
python -m scripts.migrate apply
python -m scripts.migrate verify

python -m pytest \
  tests/integration/test_phase0_postgres.py \
  tests/integration/test_conversation_migration_upgrade.py \
  tests/integration/test_feedback_privacy_integrity_postgres.py -q
```

Nao execute os testes de integracao contra um banco compartilhado sem confirmar
que eles usam schemas isolados e sem revisar a URL configurada.

## Decisao

A Fase 0 somente pode receber `approved` quando todos os gates bloqueantes
estiverem comprovados. Qualquer item `blocked`, `failed` ou sem evidencia
mantem a decisao como `not_approved`.

Os relatorios publicados no repositorio devem omitir IPs, hostnames, nomes de
snapshot, usuarios, portas administrativas, credenciais e payloads sensiveis.
