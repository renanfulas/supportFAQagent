# Mapa do projeto — supportFAQagent

Este e o **mapa vivo** do projeto: onde estamos, o que ja foi feito, o que esta
em andamento e o que falta, frente por frente. Use-o como primeiro destino para
se situar; depois v para `docs/navigation.md` (roteador por tarefa) e para o
plano da frente especifica.

> Atualize este mapa ao terminar uma fase/frente, seguindo o fluxo
> "Atualizar o estado dos planos" da skill `supportfaq-git-flow`.

Legenda de status: ✅ feito · 🟡 em andamento / parcial · ⬜ planejado / falta.

---

## Onde estamos

- **Nucleo tecnico (Fases 1–4 do MVP): ✅ concluido.** RAG simples e linear,
  provider real com fallback seguro, handoff estruturado, retrieval desacoplado
  por interface, `/chat` com `request_id`/`error_code`, feedback persistente.
- **Fase 0 (persistencia, migrations, outbox, readiness): ✅ implementada**
  (PR `#64`, `356 passed`) e validada localmente com PostgreSQL/pgvector real.
  Promocao operacional ainda **🟡 `not_approved`** ate o restore cronometrado em
  ambiente isolado passar.
- **pgvector: ✅ default operacional do staging** (`pgvector_gate.yaml` em
  `76/78`), com rollback documentado para `RETRIEVAL_BACKEND=lexical`.
- **Fase 5 (operacao/VPS/runtime): 🟡 em andamento.** Alerta de capacidade de
  disco ja entregue e ativo; falta smoke privado da Meta e acompanhamento do
  pgvector.

`n8n` foi removido do projeto e nao e gate do MVP. Ownership atual: Renan
(arquitetura, orquestracao, persistencia, pgvector, testes, seguranca, docs) e
Juliano (VPS, deploy, runtime, rede, logs, restore, apoio LangChain).

---

## Mapa das pastas de documentacao

| Pasta | O que vive aqui |
| --- | --- |
| `docs/` (raiz) | Indices transversais: este mapa, `navigation.md`, `documentation-status.md`, `product-positioning.md`, `agent-skills.md`, `references-legacy.md` |
| `docs/architecture/` | Design, fronteiras, contratos e padroes do sistema |
| `docs/setup/` | Guias de instalacao e configuracao de ambiente |
| `docs/MVP/` | Planos tecnicos majoritarios do MVP (visao geral) |
| `docs/quality-plans/` | Planos detalhados por frente do MVP |
| `docs/runbooks/` | Procedimentos operacionais de execucao |
| `docs/security/` | Planos e contratos de seguranca |
| `docs/archive/` | Concluido, substituido ou obsoleto (contexto historico) |

Fontes ativas de verdade e regra de atualizacao: `docs/documentation-status.md`.

---

## Frentes e planos

| Frente | Status | Plano / fonte | Areas principais | Validacao |
| --- | --- | --- | --- | --- |
| Nucleo RAG (Fases 1–4) | ✅ | [`MVP/mvp-plan.md`](MVP/mvp-plan.md), [`MVP/technical-implementation-plan.md`](MVP/technical-implementation-plan.md) | `app/orchestration/`, `app/retrieval/`, `app/llm/`, `app/ingestion/` | `pytest`, `run_domain_eval`, gate `76/78` |
| Fase 0 — persistencia/migrations/outbox | ✅ implementado · 🟡 promocao `not_approved` (restore drill turnkey pronto) | [`quality-plans/phase0-operational-risk-reduction.md`](quality-plans/phase0-operational-risk-reduction.md), [`runbooks/phase0-snapshot-restore.md`](runbooks/phase0-snapshot-restore.md), [`runbooks/phase0-staging-promotion-evidence.md`](runbooks/phase0-staging-promotion-evidence.md) | `app/db/`, `app/conversations/`, `app/health/`, `migrations/001-008`, `scripts/phase0_restore_validate.py` | integração PostgreSQL opt-in, `test_phase0_restore_validate` |
| pgvector (retrieval vetorial) | ✅ default de staging, rollback lexical | [`MVP/technical-implementation-plan.md`](MVP/technical-implementation-plan.md), [`runbooks/pgvector-promotion-checklist.md`](runbooks/pgvector-promotion-checklist.md) | `app/retrieval/`, `app/ingestion/pgvector_writer.py` | `pgvector_gate.yaml` |
| Persistencia em camadas (tiering) | 🟡 Fases 2-4 vivas na VPS + amostragem de qualidade concluida (2026-07-01, 0 achados de PII/PAN) + eval do recall entregue (2026-07-02, `summary_recall.yaml` 3/3 com LLM real, rotulo do prompt corrigido); falta so Fase 0 (sink R2, bloqueado por credenciais) e a metrica de custo | [`quality-plans/conversation-persistence-tiering-plan.md`](quality-plans/conversation-persistence-tiering-plan.md), [`...-tech-plan.md`](quality-plans/conversation-persistence-tiering-tech-plan.md) | `app/conversations/`, `architecture/conversation-archive-sink.md`, `runbooks/redis-session-state.md`, `runbooks/conversation-summary-batch.md` | testes fake-client + integração postgres |
| Identidade do cliente + handoff WhatsApp | ✅ Sprints 0-5 e 4b entregues e validados em staging (2026-07-01: `ENABLE_HANDOFF_CONSENT_GATE` ligado na VPS, smoke real ponta a ponta com Postgres + OTP via WhatsApp, eval com chave real 0 falhas); resta so a extensao "minion" (bloqueada no Juliano) e o hook de branching por dominio | [`quality-plans/customer-identity-whatsapp-handoff-plan.md`](quality-plans/customer-identity-whatsapp-handoff-plan.md), [`...-tech-plan.md`](quality-plans/customer-identity-whatsapp-handoff-tech-plan.md) | `app/handoff/`, `app/web_auth/`, `app/identity/`, `app/api/routes/web_handoff.py`, support inbox, `runbooks/support-team-whatsapp-notify-smoke.md` | `test_support_inbox*`, `test_support_team_notifications`, `test_web_auth`, `test_web_handoff`, `test_phase0_operational_safety` |
| Roteamento de dominio pegajoso (sticky) | ✅ seam + adapter duravel, validado em CI; plano arquivado; incremento 2026-07-02: fallback deixou de ser menu numerado e virou saudacao institucional + pergunta de esclarecimento (`fallback_routing_text`), selecao 1/2/nome segue como atalho | [`archive/implementation-plans/whatsapp-sticky-domain-routing-plan.md`](archive/implementation-plans/whatsapp-sticky-domain-routing-plan.md), [`architecture/integration-contracts.md`](architecture/integration-contracts.md) | `app/orchestration/` (domain router, channel routing, session domain store) | `test_domain_router`, `test_hermes_chat`, `test_session_domain_store(_postgres)` |
| Funil de vendas (hardening) | ✅ WS-0..WS-4 entregues e flags ligadas; decisao 2 resolvida em 2026-07-01 (`confidence_threshold` 0.55 → 0.45); falta so chegar em prod no proximo deploy | [`quality-plans/vendas-funnel-hardening-plan.md`](quality-plans/vendas-funnel-hardening-plan.md) | `domains/vendas/`, `app/handoff/`, `app/orchestration/` | `test_vendas_checkout`, `test_pii_card`, eval `vendas` |
| Meta WhatsApp nativo | 🟡 fundacao por flag (Ondas 1–3, 6); falta smoke + ativacao | [`quality-plans/meta-whatsapp-native-integration-plan.md`](quality-plans/meta-whatsapp-native-integration-plan.md), [`runbooks/meta-whatsapp-private-smoke.md`](runbooks/meta-whatsapp-private-smoke.md) | transporte Meta (`client.py`, `webhook.py`), desativado por padrao | `test_meta_whatsapp*`, activation suite |
| Hermes (adapter temporario) | ✅ cutover e2e na VPS (2026-06-29); ponte temporaria | [`quality-plans/hermes-chat-bridge-plan.md`](quality-plans/hermes-chat-bridge-plan.md), [`runbooks/hermes-chat-cutover.md`](runbooks/hermes-chat-cutover.md) | adapter Hermes (transporte externo) | `test_hermes_adapter`, `test_hermes_chat` |
| Chat web (evolucao V0->V3) | 🟡 plano-pai reconciliado 2026-07-03: V0 entregue; V1 OTP entregue como consent gate; V2 persistencia entregue e omnichannel descopada de proposito; V3 comecou (console do time entregue, status de atendimento do cliente planejado) | [`quality-plans/web-chat-evolution-plan.md`](quality-plans/web-chat-evolution-plan.md), [`quality-plans/web-chat-customer-ticket-status-plan.md`](quality-plans/web-chat-customer-ticket-status-plan.md), [`quality-plans/web-chat-v1-whatsapp-otp-spec.md`](quality-plans/web-chat-v1-whatsapp-otp-spec.md) | `app/static/`, `/web/chat`, `/web/auth`, `/web/handoff` | `test_web_chat`, `test_web_auth`, `test_web_handoff` |
| Status de atendimento p/ cliente (V3, lado cliente) | ⬜ **rebaixado 2026-07-04 (opcao C)**: painel `/web/tickets` separado nao sera construido; status vira bloco no widget web + CTA "continuar no WhatsApp"; "fechar o ciclo" migrou p/ a ponte WhatsApp | [`quality-plans/web-chat-customer-ticket-status-plan.md`](quality-plans/web-chat-customer-ticket-status-plan.md), [`quality-plans/web-chat-customer-ticket-status-tech-plan.md`](quality-plans/web-chat-customer-ticket-status-tech-plan.md) | bloco no widget web (a criar), `app/identity/current.py` | — |
| Ponte WhatsApp <-> console (atendimento humano, 2 numeros) | 🟡 **Fases 1 e 2 implementadas em codigo 2026-07-05** (dark, `ENABLE_WHATSAPP_SUPPORT_NUMBER=false`): chat humano in-window, templates, notificacao proativa (assumiu/resolvido), e-mail paralelo com opt-out (transporte real ainda nao implementado, rota `disabled` de proposito). Falta so provisionamento externo na Meta (numero de suporte + webhook + aprovacao de 4 templates, Juliano) p/ smoke real, e o provedor de e-mail (Juliano). **Fase 3 (unificacao de identidade): pesquisa de codigo concluida 2026-07-06, mecanismo NAO decidido de proposito** (decisao de consentimento entre unir tudo automaticamente vs. so via OTP web -- ver secao propria no tech-plan) | [`quality-plans/whatsapp-support-bridge-tech-plan.md`](quality-plans/whatsapp-support-bridge-tech-plan.md) | `app/support/wa_binding.py`, `app/support/whatsapp_bridge.py`, `app/support/customer_preferences.py`, `app/notifications/customer_status.py`, `app/support/transitions.py`, `app/api/routes/meta_whatsapp.py`, `app/api/routes/web_support.py`, `scripts/dispatch_outbox.py`, migrations 016/017/018 | `test_support_whatsapp_bridge`, `test_dispatch_outbox_whatsapp`, `test_customer_status_notifications`, `test_support_transcript` |
| Console do time (tickets + metricas) | 🟡 Fases A, B e C entregues em codigo (2026-07-03: migrations 014/015, auth OTP staff com lembrete de dispositivo, fila com semaforo SLA e `waiting_seconds` real, transicoes auditadas com CAS, dono do caso, painel de metricas — backlog/throughput/escalation/feedback/response_times —, `manage_staff.py`, readiness + schema contract, contrato da fachada); faltam smoke em staging e UI `/team` (Juliano) | [`quality-plans/support-team-console-plan.md`](quality-plans/support-team-console-plan.md), [`...-tech-plan.md`](quality-plans/support-team-console-tech-plan.md), [`runbooks/support-console-smoke.md`](runbooks/support-console-smoke.md) | fachada `/web/support/*` (auth OTP staff dedicado, fila com semaforo SLA, transicoes, metricas), UI interna `/team` no `ask-host-genius` | `test_support_staff_auth`, `test_support_sla`, `test_support_transitions`, `test_support_repository_console`, `test_support_metrics`, `test_web_support_console` |
| Observabilidade e seguranca | ✅ baseline (request_id, sanitizacao, rate limit, confinamento) | [`architecture/observability.md`](architecture/observability.md), [`security/`](security/) | `app/core/`, `app/api/` | `test_request_observability`, `test_privacy`, `tests/security/` |
| Operacao Fase 5 (VPS/runtime) | 🟡 em andamento | [`setup/configuracaoVPS.md`](setup/configuracaoVPS.md), [`runbooks/vps-controlled-runtime.md`](runbooks/vps-controlled-runtime.md), [`runbooks/vps-capacity-and-docker-cleanup.md`](runbooks/vps-capacity-and-docker-cleanup.md) | `scripts/`, runtime da VPS | preflight de runtime, smoke de staging |

---

## O que falta agora (proxima ordem tecnica)

1. **Restore cronometrado** em ambiente isolado a partir do snapshot, medindo
   `RPO <= 24h` / `RTO <= 4h`, para promover a Fase 0. O run-sheet turnkey e o
   helper read-only (`scripts/phase0_restore_validate.py`) estao prontos e ja
   foram ensaiados localmente (dump→restore real); falta a execucao no host
   isolado, que depende do provedor/runtime (Juliano)
   (`runbooks/phase0-snapshot-restore.md`, `runbooks/phase0-staging-promotion-evidence.md`).

   > **Observacao:** o ensaio local usou um cluster PostgreSQL descartavel e
   > sintetico (nao o snapshot real do provedor nem o host isolado da VPS).
   > Isso comprova a ferramenta (run-sheet + helper + calculo de RTO/RPO), nao
   > o gate em si. A Fase 0 continua `not_approved` ate o Juliano rodar o
   > restore real. Esta frente esta **encerrada do lado de preparacao** (#113,
   > #114); o proximo passo e execucao pura, fora do escopo de arquitetura,
   > contratos ou testes.
2. **Smoke privado da Meta WhatsApp** antes de qualquer ativacao real
   (`runbooks/meta-whatsapp-private-smoke.md`).
3. ~~Capacidade de disco da VPS: alerta + politica de limpeza de cache Docker~~ —
   **ja entregue** (PR #68) e **confirmado ativo em 2026-07-02**:
   `supportfaq-capacity-alert.timer` roda a cada ~15min na VPS via systemd,
   thresholds `75%`/`85%`/`<2GiB livre`, alerta por WhatsApp (rota Hermes
   `supportfaq-alerts`) so em `critical`, guarda de volumes PostgreSQL/pgvector
   contra `docker volume prune`. Estado atual verificado: `65,3%` usado,
   `5,3 GiB` livres, status `ok`, 0 disparos — sem risco ativo. Ver
   `runbooks/vps-capacity-and-docker-cleanup.md`.

   > **Achados paralelos investigados e resolvidos em 2026-07-02** (fora do
   > escopo do supportFAQagent, app `ask_host_genius` no mesmo host):
   > `npm cache clean --force` + limpeza de `~/.bun/install/cache` liberaram
   > ~1,2 GiB (disco foi de `69%`/5,5 GiB livres para `63%`/6,5 GiB livres).
   > Container Docker `ask_host_genius` (criado 11/06) estava **parado de
   > servir trafego** desde que o deploy real migrou para
   > `/opt/ask-host-genius` + `systemd` + `bun` (o mapeamento de porta `5173`
   > do container conflitava com o processo do host, sem healthcheck nem log
   > em 48h) — parado com `docker stop` (nao removido; reversivel).
   > **Processo orfao do `ask-host-genius.service` removido**: o `MainPID`
   > que o systemd rastreava era um processo de 19/06 que, no proprio log,
   > nunca serviu trafego real — na subida encontrou a porta `5173` ja
   > ocupada (pelo container Docker acima, criado antes, em 11/06) e caiu
   > para outra porta (`"Port 5173 is in use, trying another one..."`); quem
   > sempre serviu de fato foi um segundo processo de 23/06, iniciado fora do
   > systemd. `systemctl stop ask-host-genius.service` removeu a arvore
   > orfa (verificado: PIDs extintos) sem tocar no processo de 23/06 — dois
   > grupos de processo isolados, confirmado via `ps --forest` antes de agir.
   > `chat.ordens.com.br` verificado `HTTP 200` antes e depois, mesmo `pid`
   > ainda escutando a `5173`. Estado do systemd agora reflete a realidade
   > (`failed`, nao mais `active` falso). Reversao: `systemctl start
   > ask-host-genius.service` (nao houve loop de restart porque `stop`
   > explicito nao aciona o `Restart=always`). Residual, fora do escopo desta
   > doc: o processo de 23/06 que serve de verdade continua sem supervisao do
   > systemd; corrigir isso (recriar o `ExecStart` apontando pra ele, ou
   > redeploy limpo) e trabalho do Juliano quando quiser.
4. **Fase 0 do tiering (archive sink R2)**: unico item de persistencia em camadas
   ainda desligado, bloqueado por credenciais Cloudflare R2 (bucket/endpoint/chaves).
   Redis (Fase 2), batch+recall (Fases 3-4) e o eval do recall (2026-07-02,
   `evals/summary_recall.yaml`, confirmado tambem na VPS contra pgvector + LLM
   reais) ja estao entregues. Resta so a metrica de custo da sumarizacao (ver
   `quality-plans/conversation-persistence-tiering-tech-plan.md` Fase 4).
5. **Minion de hospedagem**: contrato HTTP ja escrito adiantado
   (`architecture/integration-contracts.md`, "Minion de diagnostico"), v1
   somente leitura/diagnostico. BLOQUEADO no Juliano so para a implementacao do
   minion em si e o alinhamento leitura-vs-escrita da v1 (ver
   `customer-identity-whatsapp-handoff-plan.md`). O hook de branching por
   dominio no `HandoffService`/`ChatFlowService` ainda nao foi escrito.
6. **Evolucao do chat web**: plano-pai `web-chat-evolution-plan.md` reconciliado
   em 2026-07-03 (V-phases nao mapeavam mais o que foi construido). Proxima
   fatia de V3 ja planejada: **status de atendimento para o cliente**
   (`quality-plans/web-chat-customer-ticket-status-plan.md`, Fase A read-only) —
   nenhuma fase iniciada. Ainda por planejar na V3: loop feedback->base de
   conhecimento, roteamento multi-dominio no web chat e direitos LGPD do titular.
   Decisao 2026-07-02: o frontend segue no `ask-host-genius` (proxy Nginx +
   contrato `/web/*`); nao havera frontend proprio no backend.
7. **Console do time (tickets + metricas)**: frente nova planejada em
   2026-07-02 — entrega incremental da visao V3 do chat web sobre o support
   inbox existente. Fase A (auth OTP staff dedicado + fila com semaforo SLA)
   e o primeiro passo implementavel; planos em
   `quality-plans/support-team-console-plan.md` e `...-tech-plan.md`.

Itens ja fechados (funil de vendas, enriquecimento de push do support inbox,
Sprint 4b do consentimento LGPD, eval do recall da Fase 4) ficam registrados
nos planos de cada frente na tabela acima e em `quality-plans/`; nao repetidos
aqui para o mapa nao acumular ruido historico.

---

## Como manter este mapa atualizado

Ao concluir uma fase ou frente, **antes do commit/PR**, registre o avanco
(veja a secao "Atualizar o estado dos planos" em
`.agents/skills/supportfaq-git-flow/SKILL.md`):

1. Atualize o plano da frente em `docs/quality-plans/<frente>.md`: marque o que
   foi entregue e o que ainda falta.
2. Atualize a linha da frente na tabela acima (status e nota).
3. Atualize `docs/documentation-status.md` se mudou status, ownership, contrato,
   migration ou operacao.

Caminhos antigos de documentos movidos: `docs/references-legacy.md`.
