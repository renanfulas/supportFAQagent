# Estado Da Documentacao

## Fontes Ativas De Verdade

Use estes documentos para tomar decisoes atuais:

- `README.md`: status publico resumido;
- `docs/project-map.md`: estado de cada frente (feito, em andamento, falta) e
  mapa das pastas de documentacao;
- `docs/MVP/mvp-plan.md`: escopo e fase atual;
- `docs/MVP/technical-implementation-plan.md`: estado tecnico e ownership;
- `docs/quality-plans/phase0-operational-risk-reduction.md`: gates da Fase 0;
- `docs/runbooks/phase0-staging-promotion-evidence.md`: evidencia obrigatoria
  para promocao;
- `docs/setup/environments.md`: fronteiras entre local, staging e producao;
- `docs/architecture/integration-contracts.md`: contratos HTTP e de integracao;
- `docs/navigation.md`: mapa atual do repositorio.
- `docs/archive/README.md`: indice de planos concluidos e documentos
  historicos, com seus substitutos ativos.

## Estado Consolidado

- Fases 1-4 do nucleo tecnico: concluidas para o MVP;
- Fase 0: implementada, integrada pelo PR `#64` e validada localmente com
  PostgreSQL/pgvector real e `356 passed`;
- Fase 0 operacional: `not_approved` ate executar restore cronometrado em
  ambiente isolado e medir `RPO <= 24h` / `RTO <= 4h`;
- Fase 5: em andamento, concentrada em operacao, capacidade, observabilidade e
  acompanhamento do pgvector como default de staging. `n8n` foi removido do
  projeto (assets `deploy/n8n/`, aliases de config e runbooks dedicados) e nao
  faz parte do plano operacional.

## Proxima Ordem Tecnica

1. Executar restore cronometrado em ambiente isolado a partir do snapshot.
2. Validar PostgreSQL, API, migrations, readiness, pgvector, outbox e volumes
   do agente no ambiente restaurado.
3. Medir `RPO <= 24h` e `RTO <= 4h`.
4. Gerar o relatorio operacional final e decidir promocao da Fase 0.

Os quatro hardenings locais anteriormente bloqueantes foram concluidos e
validados em 15/06/2026. Consulte
`docs/runbooks/local-phase0-hardening-report-2026-06-15.md`.

Em 18/06/2026, o acesso SSH ao staging voltou, o disco foi reduzido de `100%`
para `81%`, o checkout remoto foi promovido para `61ea039`, as migrations
`001-008` foram verificadas, readiness passou, os testes PostgreSQL opt-in
passaram em banco descartavel e a `pgvector_gate.yaml` fechou em `76/78`.
Em 19/06/2026, `RETRIEVAL_BACKEND=pgvector` foi confirmado como default
operacional do staging, com readiness de retrieval `pgvector` ok e rollback
documentado para `RETRIEVAL_BACKEND=lexical`. A promocao operacional continua
`not_approved` somente porque o restore cronometrado em ambiente isolado ainda
nao foi executado. Consulte
`docs/runbooks/phase0-staging-promotion-evidence.md`.

Em 01/07/2026, a migration `013_customer_contact_and_consent.sql` foi aplicada
no staging e `ENABLE_HANDOFF_CONSENT_GATE=true` entrou em operacao, com smoke
real ponta a ponta (Postgres + OTP via WhatsApp) e `run_domain_eval
suporte-vps-whatsapp` com chave real + pgvector sem falhas. Evidencias em
`docs/quality-plans/customer-identity-whatsapp-handoff-plan.md` (Sprint 4b).

Em 02/07/2026, tres frentes fecharam do lado de codigo:

- **Hardening do funil de vendas**: `confidence_threshold` do dominio `vendas`
  baixado de `0.55` para `0.45` (decisao 2, com base no dado do WS-0). Evals e
  suites de confinamento verdes; muda comportamento em prod so no proximo
  deploy/restart. Ver `docs/quality-plans/vendas-funnel-hardening-plan.md`.
- **Enriquecimento de push do support inbox (Sprint 5)**: a notificacao adiada
  pelo gate de consentimento LGPD agora carrega o contato autorizado (nome,
  e-mail, final do WhatsApp verificado); o detalhe do inbox expoe o mesmo bloco
  `customer` via join com `customers`; `POST /web/handoff/consent` devolve
  `customer_name`. Ver `docs/quality-plans/customer-identity-whatsapp-handoff-plan.md`
  (Sprint 5) e `docs/architecture/integration-contracts.md`.
- **Eval do recall (tiering Fase 4)**: suite opt-in
  `domains/suporte-vps-whatsapp/evals/summary_recall.yaml` valida que o resumo
  recuperado melhora e nao polui a resposta. O primeiro run com LLM real
  revelou que o rotulo antigo do bloco de resumo no prompt fazia o modelo
  recusar usar o recall; corrigido em `app/orchestration/prompt_builder.py`.
  Confirmado tambem na VPS (deploy ate `c57248e`) contra pgvector + LLM reais,
  3/3. Ver `docs/quality-plans/conversation-persistence-tiering-tech-plan.md`
  (Fase 4).

Em 03/07/2026, as Fases A, B e C do console do time entraram no codigo:
migration `014_support_console_staff.sql` (staff_members, staff_sessions,
staff_login_hints), fachada `/web/support/*` (auth por OTP WhatsApp dedicado
com lembrete de dispositivo + fila com semaforo de SLA), `scripts/manage_staff.py`,
componente `support_console` no readiness e objetos da 014 no schema contract;
migration `015_support_case_events.sql` (`support_cases.assignee_staff_id` +
tabela de eventos), `POST /web/support/cases/{case_id}/transition` com
compare-and-swap e evento auditavel na mesma transacao, `waiting_seconds` real
plugado em `compute_sla`, filtro `assignee=me` e historico de eventos no
detalhe; `GET /web/support/metrics` (backlog reusando `compute_sla`,
throughput diario zero-fillado no fuso do time, escalation reasons, feedback
com `helpful_rate`/`unknown_domain_count`, medianas de tempo de resposta).
Tudo dark por padrao atras de `ENABLE_SUPPORT_CONSOLE`; nada aplicado
em staging ainda. Contrato em `docs/architecture/integration-contracts.md`,
smoke em `docs/runbooks/support-console-smoke.md`, estado em
`docs/quality-plans/support-team-console-tech-plan.md`.

Em 05/07/2026, a Fase 1 da ponte WhatsApp<->console foi implementada em
codigo: migrations `016_case_whatsapp_bindings.sql` (binding cifrado do
`wa_id`, retencao dupla), `017_support_case_events_actor_kind.sql` (ator
generico staff/customer/system) e `018_messages_delivery_status.sql` (status
de entrega por mensagem); cifra/token em `app/support/wa_binding.py`
(`SUPPORT_WA_ENC_KEY`, `SUPPORT_WA_TOKEN_SECRET`); handler de inbound sem RAG
e compositor do atendente em `app/support/whatsapp_bridge.py`; roteamento por
`phone_number_id` no webhook Meta (modo-por-numero); deep link no handoff
(`support_deep_link` em `WebChatResponse`/`HandoffConsentResponse`);
dispatcher com selecao de numero (`phone_number_kind`) e write-back do
`meta_message_id`; componente `whatsapp_bridge` no readiness. Tudo dark por
padrao atras de `ENABLE_WHATSAPP_SUPPORT_NUMBER`; nada aplicado em staging
ainda (falta o numero de suporte provisionado na Meta, dono: Juliano).
Contrato em `docs/architecture/integration-contracts.md`, smoke em
`docs/runbooks/whatsapp-support-bridge-smoke.md`, estado em
`docs/quality-plans/whatsapp-support-bridge-tech-plan.md`.

No mesmo dia (05/07/2026), a Fase 2 tambem foi implementada em codigo, sem
migration nova: `whatsapp.template.requested` e `email.message.requested` no
outbox (a rota de e-mail fica com transporte `disabled` de proposito -- nenhum
provedor foi decidido; Juliano liga so trocando
`OUTBOX_EMAIL_DELIVERY_TRANSPORT`); compositor aceita `template` opcional para
responder fora da janela de 24h (`precisa_info`/`reengajar`, staff-triggered);
notificacao proativa em `app/support/transitions.py` para `claim` (->
`atendente_assumiu`) e `close` (-> `ticket_resolvido` com resumo de
`context_snapshot_sanitized.summary` -- nao `conversation_summaries`, que e
batch e pode nao estar pronto no momento do fechamento); renderer puro em
`app/notifications/customer_status.py`; opt-out de e-mail em
`app/support/customer_preferences.py` (primeiro leitor real de
`customer_preferences` no projeto; default opt-in). 856 testes verdes.
Continua dark; falta a aprovacao dos 4 templates na WABA e o provedor de
e-mail (dono: Juliano).

Em 06/07/2026, a Fase 3 (unificacao de identidade, opcional) foi decidida --
Opcao B, opt-in via OTP web, escolhida sobre a Opcao A (vincular todo inbound
nativo automaticamente) para preservar o WhatsApp nativo pseudonimo por
padrao -- e implementada em codigo no mesmo dia: migration
`019_otp_challenge_native_link.sql` (duas colunas efemeras em
`otp_challenges` para carregar o hash nativo recalculado de `start()` a
`confirm()`, unico jeito de contornar o telefone bruto nao sobreviver entre
as duas chamadas); formula pura + repositorio de backfill em
`app/identity/native_history_link.py`; wiring em
`app/web_auth/service.py`/`storage.py`; orquestracao best-effort na rota
`POST /web/auth/whatsapp/confirm`; componente `native_identity_link` no
readiness. Dark por padrao (`ENABLE_NATIVE_IDENTITY_LINK=false`). Sem
mudanca no contrato HTTP publico do OTP. 871 testes verdes. Contrato em
`docs/architecture/integration-contracts.md`, estado em
`docs/quality-plans/whatsapp-support-bridge-tech-plan.md`. Sem dependencia
externa (Juliano) nesta fase.

## Documentos Historicos

Planos antigos podem citar Alexandre e Silotto ou descrever entregas que ja
foram incorporadas. Eles devem ser lidos como registro historico quando o
proprio documento declarar essa natureza.

Nao apague documentos historicos somente por conterem ownership antigo. Corrija
ou mova para `docs/archive/` quando houver risco de um operador seguir
instrucoes obsoletas.

## Regra De Atualizacao

Uma mudanca que altera status, ownership, contrato HTTP, migration ou operacao
deve atualizar primeiro as fontes ativas acima. Runbooks executaveis nunca
podem depender apenas de contexto historico.
