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
- **Fase 5 (operacao/VPS/runtime): 🟡 em andamento.** Capacidade de disco,
  monitoramento, smoke privado da Meta e acompanhamento do pgvector.

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
| Fase 0 — persistencia/migrations/outbox | ✅ implementado · 🟡 promocao `not_approved` | [`quality-plans/phase0-operational-risk-reduction.md`](quality-plans/phase0-operational-risk-reduction.md), [`runbooks/phase0-staging-promotion-evidence.md`](runbooks/phase0-staging-promotion-evidence.md) | `app/db/`, `app/conversations/`, `app/health/`, `migrations/001-008` | integração PostgreSQL opt-in, `356 passed` |
| pgvector (retrieval vetorial) | ✅ default de staging, rollback lexical | [`MVP/technical-implementation-plan.md`](MVP/technical-implementation-plan.md), [`runbooks/pgvector-promotion-checklist.md`](runbooks/pgvector-promotion-checklist.md) | `app/retrieval/`, `app/ingestion/pgvector_writer.py` | `pgvector_gate.yaml` |
| Persistencia em camadas (tiering) | 🟡 seams implementados, dark por flag (2026-06-29) | [`quality-plans/conversation-persistence-tiering-plan.md`](quality-plans/conversation-persistence-tiering-plan.md), [`...-tech-plan.md`](quality-plans/conversation-persistence-tiering-tech-plan.md) | `app/conversations/`, `architecture/conversation-archive-sink.md`, `runbooks/redis-session-state.md`, `runbooks/conversation-summary-batch.md` | testes fake-client + integração postgres |
| Identidade do cliente + handoff WhatsApp | 🟡 Sprints 1–4 iniciais OK (PG opt-in); falta enriquecimento de push | [`quality-plans/customer-identity-whatsapp-handoff-plan.md`](quality-plans/customer-identity-whatsapp-handoff-plan.md) | `app/handoff/`, support inbox, `runbooks/support-team-whatsapp-notify-smoke.md` | `test_support_inbox*`, `test_support_team_notifications` |
| Roteamento de dominio pegajoso (sticky) | ✅ seam + adapter duravel, validado em CI | [`quality-plans/whatsapp-sticky-domain-routing-plan.md`](quality-plans/whatsapp-sticky-domain-routing-plan.md) | `app/domain_engine/` (session domain store) | `test_session_domain_store(_postgres)` |
| Funil de vendas (hardening) | 🟡 em andamento (achados de smoke) | [`quality-plans/vendas-funnel-hardening-plan.md`](quality-plans/vendas-funnel-hardening-plan.md) | `domains/vendas/`, `app/handoff/`, `app/orchestration/` | `test_vendas_checkout`, `test_pii_card`, eval `vendas` |
| Meta WhatsApp nativo | 🟡 fundacao por flag (Ondas 1–3, 6); falta smoke + ativacao | [`quality-plans/meta-whatsapp-native-integration-plan.md`](quality-plans/meta-whatsapp-native-integration-plan.md), [`runbooks/meta-whatsapp-private-smoke.md`](runbooks/meta-whatsapp-private-smoke.md) | transporte Meta (`client.py`, `webhook.py`), desativado por padrao | `test_meta_whatsapp*`, activation suite |
| Hermes (adapter temporario) | ✅ cutover e2e na VPS (2026-06-29); ponte temporaria | [`quality-plans/hermes-chat-bridge-plan.md`](quality-plans/hermes-chat-bridge-plan.md), [`runbooks/hermes-chat-cutover.md`](runbooks/hermes-chat-cutover.md) | adapter Hermes (transporte externo) | `test_hermes_adapter`, `test_hermes_chat` |
| Chat web (evolucao / OTP) | 🟡 V0 publica incorporada; fases seguintes planejadas | [`quality-plans/web-chat-evolution-plan.md`](quality-plans/web-chat-evolution-plan.md), [`web-chat-v1-whatsapp-otp-spec.md`](quality-plans/web-chat-v1-whatsapp-otp-spec.md) | `app/static/`, `POST /web/chat`/`/web/feedback`, web auth | `test_web_chat`, `test_web_auth` |
| Observabilidade e seguranca | ✅ baseline (request_id, sanitizacao, rate limit, confinamento) | [`architecture/observability.md`](architecture/observability.md), [`security/`](security/) | `app/core/`, `app/api/` | `test_request_observability`, `test_privacy`, `tests/security/` |
| Operacao Fase 5 (VPS/runtime) | 🟡 em andamento | [`setup/configuracaoVPS.md`](setup/configuracaoVPS.md), [`runbooks/vps-controlled-runtime.md`](runbooks/vps-controlled-runtime.md), [`runbooks/vps-capacity-and-docker-cleanup.md`](runbooks/vps-capacity-and-docker-cleanup.md) | `scripts/`, runtime da VPS | preflight de runtime, smoke de staging |

---

## O que falta agora (proxima ordem tecnica)

1. **Restore cronometrado** em ambiente isolado a partir do snapshot, medindo
   `RPO <= 24h` / `RTO <= 4h`, para promover a Fase 0
   (`runbooks/phase0-snapshot-restore.md`, `runbooks/phase0-staging-promotion-evidence.md`).
2. **Smoke privado da Meta WhatsApp** antes de qualquer ativacao real
   (`runbooks/meta-whatsapp-private-smoke.md`).
3. **Capacidade de disco da VPS**: alerta + politica de limpeza de cache Docker,
   preservando volumes do PostgreSQL (`runbooks/vps-capacity-and-docker-cleanup.md`).
4. **Promover as camadas de persistencia hoje dark** (archive sink, Redis de
   sessao, batch de sumarizacao) conforme o tech-plan, quando o operacional pedir.
5. **Fechar frentes parciais**: enriquecimento de push do support inbox
   (identidade + handoff) e hardening restante do funil de vendas.

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
