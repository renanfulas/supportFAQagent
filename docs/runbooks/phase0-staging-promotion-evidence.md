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
| Handoff | simular outbox indisponivel e entrega falha | chat continua disponivel, retry e `dead_letter` observaveis | sim |
| Idempotencia externa | repetir chamada com mesma chave | dispatcher ou consumidor HTTP nao produz segunda acao logica | sim |
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
6. Validar handoff e idempotencia externa quando houver consumidor HTTP ativo.
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

## Execucao De Staging 2026-06-18

Decisao: `not_approved`.

Evidencias sanitizadas:

- acesso SSH ao staging voltou a responder;
- autenticacao por chave nao esta configurada no ambiente local, mas acesso
  administrativo foi validado por canal privado;
- disco raiz estava em `100%` e foi reduzido para `81%` com limpeza segura de
  cache/journal, remocao de imagem Docker sem container ativo e desativacao
  temporaria dos containers/imagens de `n8n` sem remover volumes;
- nenhum volume, banco ou dado persistente foi removido;
- checkout remoto do agente esta atrasado em relacao a `origin/main`;
- scripts da Fase 0 (`scripts.migrate` e `scripts.check_readiness`) ainda nao
  existem no checkout implantado;
- nenhum `git pull`, migration, restart, teste destrutivo ou restore foi
  executado porque nao havia snapshot confirmado;
- a VPS consegue consultar o commit atual de `origin/main`, entao o bloqueio
  principal deixou de ser conectividade/capacidade e passou a ser
  snapshot/deploy controlado.

Proxima decisao operacional:

- executar restore cronometrado em ambiente isolado;
- somente depois mudar a decisao operacional para `approved`.

## Execucao De Staging 2026-06-18 - Promocao Parcial

Decisao: `not_approved`.

Resultado sanitizado:

- snapshot foi tratado como confirmado por ordem operacional do responsavel;
- checkout remoto promovido para `origin/main` no commit `61ea039`;
- `.env` remoto recebeu somente variaveis obrigatorias ausentes da Fase 0, com
  backup privado criado antes da alteracao;
- `scripts.staging_phase0_preflight --snapshot-confirmed` retornou
  `ready_for_migration_review: true`;
- banco oficial recebeu `baseline` seguro de `001` e `002`;
- migrations `003` a `008` aplicadas pelo fluxo expand/backfill/contract;
- segunda execucao de `apply` foi idempotente;
- `scripts.migrate verify` confirmou `8` migrations aplicadas;
- `scripts.check_readiness` retornou `status: ok` para banco, migrations,
  retrieval e outbox;
- testes PostgreSQL opt-in rodaram em banco descartavel separado e retornaram
  `20 passed`;
- `compileall` de `app`, `scripts` e `tests` passou;
- ingestao pgvector do dominio processou `13` documentos e `24` chunks;
- `pgvector_gate.yaml` retornou `76/78`, acima do criterio normal `>=74/78`;
- falhas restantes da gate: `vps-049-disco-cheio` e
  `vps-091-banco-consome-disco`, ambas por `unexpected_escalation` com
  `low_confidence`;
- decisao operacional consolidada gerada em staging:
  snapshot `passed`, preflight `passed`, migrations `passed`,
  postgres_concurrency `passed`, pgvector_gate `passed`, restore `blocked`;
- disco permaneceu em `81%`;
- containers ativos ao final: API/frontend existente, PostgreSQL pgvector e
  servico externo nao relacionado ao agente;
- `n8n` foi removido do plano operacional atual; seus containers permanecem
  desativados e os volumes historicos foram preservados apenas para seguranca.

## Decisao De Retrieval 2026-06-19 - pgvector Default Em Staging

`RETRIEVAL_BACKEND=pgvector` passa a ser o default operacional do staging.

Evidencias sanitizadas:

- `.env` privado do staging confirmado com `RETRIEVAL_BACKEND=pgvector`;
- `DATABASE_URL` e provider de embeddings presentes;
- `scripts.check_readiness` retornou `status: ok` com retrieval `pgvector`;
- smoke HTTP privado retornou `3/3`;
- `pgvector_gate.yaml` retornou `76/78`, acima do criterio normal `>=74/78`;
- falhas restantes seguem conhecidas e concentradas em perguntas de disco com
  `unexpected_escalation`.

Rollback:

- alterar `RETRIEVAL_BACKEND=lexical` no `.env` privado do staging;
- reiniciar o runtime;
- rodar smoke `/health`, `/domains` e `/chat`;
- registrar relatorio sanitizado;
- nao apagar tabelas, chunks ou embeddings pgvector sem decisao explicita.

Pendencias bloqueantes:

- restore cronometrado ainda nao foi executado em ambiente isolado;
- a Fase 0 operacional continua `not_approved` ate o restore passar dentro de
  `RPO <= 24h` e `RTO <= 4h`.

## Decisao De Escopo 2026-06-18 - n8n Removido

`n8n` nao e mais parte do plano operacional atual do MVP. Portanto:

- o antigo smoke de `n8n` deixa de ser gate bloqueante da Fase 0;
- a remocao temporaria dos containers de `n8n` para liberar disco deixa de ser
  pendencia de promocao;
- os volumes historicos de `n8n` podem ser preservados ate uma decisao
  explicita de descarte, mas nao sao requisito para aprovar a Fase 0;
- o unico gate operacional bloqueante restante e o restore cronometrado em
  ambiente isolado.

## Tentativa De Restore 2026-06-18

Decisao: `blocked`.

Evidencias sanitizadas:

- o staging oficial permanece online e validado no commit `61ea039`;
- o filesystem raiz permanece em `81%`;
- nao ha CLI de provedor disponivel na VPS para criar ou restaurar snapshot;
- nao ha variaveis de ambiente de provedor/snapshot/restore disponiveis na
  sessao remota;
- nao foi informado um host isolado restaurado para validar;
- o restore nao foi executado porque restaurar por cima do staging oficial
  destruiria o ambiente validado e invalidaria a propria prova de recuperacao.

Proximo requisito externo:

- restaurar o snapshot em uma VPS ou ambiente isolado pelo painel/provedor;
- informar o acesso privado ao ambiente restaurado;
- executar no ambiente restaurado `scripts.migrate verify`,
  `scripts.check_readiness`, validacao de pgvector/outbox/volumes e registrar
  tempos para medir `RPO <= 24h` e `RTO <= 4h`.
