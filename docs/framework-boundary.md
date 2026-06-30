# Fronteira de Framework e Contrato de Extensão

Este projeto é um **motor reusável de agente de atendimento**: o núcleo é
agnóstico de domínio e os domínios entram como **plugin de dados/config**, sem
tocar no core. Este documento desenha a **fronteira** (o que é core vs o que é
plugin), cataloga os **seams** (pontos de extensão de infraestrutura) e fixa as
**regras** que mantêm isso framework-able conforme cresce.

Complementa — não substitui:
- [`docs/domain-contract.md`](domain-contract.md) — o plugin de domínio em detalhe
  (campos de `domain.yaml`, como criar um domínio).
- [`docs/architecture.md`](architecture.md) — os módulos e camadas.
- [`docs/quality-plans/conversation-persistence-tiering-plan.md`](quality-plans/conversation-persistence-tiering-plan.md)
  — a decisão de persistência (âncora síncrona + cache).

---

## 1. Tese

```
core agnóstico de domínio  +  domínios como plugin (dados/config)  +  infra atrás de seams
```

Um domínio novo (suporte, vendas, onboarding, …) deve entrar **sem mudar o core** e
**sem mexer em outro domínio**. Se adicionar um domínio exige `if domain == "x"` no
core, a fronteira foi violada.

## 2. Os dois eixos de extensão

| Eixo | O que estende | Como | Detalhe |
| --- | --- | --- | --- |
| **A — Comportamento & conhecimento** | o que o agente *faz/sabe* num domínio | **plugin de domínio** em `domains/<x>/`: `domain.yaml`, `knowledge/`, `prompts/`, `evals/` — **sem código** | `domain-contract.md` |
| **B — Infraestrutura** | *onde/como* o motor persiste, busca, entrega | **seams** (Protocols/adapters): troca de backend sem mudar chamador | §4 abaixo |

Os dois eixos são ortogonais: um domínio não escolhe infra; um backend não conhece
domínio.

## 3. O que é CORE (invariantes — agnóstico, nunca muda por domínio)

Estes módulos resolvem o problema de **todos** os domínios e não carregam regra de
nenhum (ver `architecture.md`):

- Roteamento por domínio (`app/orchestration`, `app/domain_engine`).
- Retrieval/RAG (`app/retrieval`) e construção de prompt (`app/orchestration/prompt_builder.py`).
- Handoff, confinamento e taxonomia de escalonamento (`app/handoff`).
- Persistência: write-through como fonte da verdade + outbox (`app/conversations`, `app/db`).
- Observabilidade sanitizada (`app/core`, logs estruturados).

O core **lê** comportamento do domínio (via `domain.yaml`/`DomainConfig`); ele nunca
**embute** comportamento de um domínio.

## 4. Catálogo de seams (extensão de infraestrutura)

Cada seam é um `Protocol` com default seguro e impl operacional trocável por flag —
o padrão do `ConversationArchiveSink`.

| Seam (Protocol) | Troca | Default → operacional |
| --- | --- | --- |
| `VectorStore` / `PgVectorSearchBackend` (`app/retrieval`) | backend de busca | lexical/fake → pgvector |
| `SessionDomainStore` (`app/orchestration/session_domain_store.py`) | memória de roteamento sticky | in-memory → `PgSessionDomainStore` |
| `SessionStateStore` (`app/conversations/session_state.py`) | estado quente de sessão | in-memory → `RedisSessionStateStore` |
| `ConversationArchiveSink` (`app/conversations/archive_sink.py`) | backup off-box | arquivo NDJSON → S3/R2 |
| `SummaryProvider` (`app/conversations/summary.py`) | LLM do batch de resumo | injetável → `LLMWrapper` |
| `OtpDeliveryAdapter`, `WebAuthStore` (`app/web_auth`) | entrega de OTP / storage de auth | stub/memory → Meta/Postgres |
| `EmbeddingBatchProvider`, `ConnectionFactory` (`app/ingestion`) | embeddings/conexão de ingestão | injetável → provider real |

Adicionar um backend = nova classe que satisfaz o Protocol + branch no factory
`build_*_from_env`. **Nunca** muda o chamador nem o schema.

## 5. Regras que mantêm o framework (não-negociáveis)

- **R1 — Comportamento de domínio mora em `domains/`.** Nunca hardcode regra de um
  domínio no core. Sem `if domain == "..."` em `app/`.
- **R2 — Estado específico de domínio é namespaced por domínio.** As chaves de
  sessão já são `(domain, channel, session_hash)`. O `SessionState` **compartilhado**
  não carrega campos de um único domínio (ex.: *discovery slots* de vendas). Estado
  de domínio vai num namespace/sub-objeto do próprio domínio, não no contrato comum.
- **R3 — Tudo externo/lento/stateful atrás de seam** com default seguro e flag de
  rollback sem redeploy.
- **R4 — Persistência é âncora + cache, não pipeline.** Postgres = âncora síncrona
  (verdade); RAM/Redis = cache *sobre* a âncora; off-box = backup assíncrono via
  outbox. O dado não *atravessa* camadas em série; o cache é consulta lateral
  (fail-open). Ver o plano de tiering.
- **R5 — Privacidade por construção.** Nunca `session_id`/PII cru em chave, log ou
  store; isolamento por `domain` em todo índice/tabela.

## 6. Contrato de extensão — adicionar um domínio novo

O domínio **fornece** (eixo A, sem código):

1. `domains/<x>/domain.yaml` — persona, objetivo, confinamento, flags, threshold,
   roteamento (ver `domain-contract.md`).
2. `domains/<x>/knowledge/` — artigos/FAQs versionados.
3. `domains/<x>/prompts/` — `system.txt` (+ `style.txt` opcional).
4. `domains/<x>/evals/` — `cases.yaml` + confinamento, que provam o comportamento.

O core **entrega de graça** (eixo B, sem o domínio pedir): roteamento, retrieval,
prompt-building com confinamento, handoff/escalonamento, persistência write-through
+ outbox + backup, sumarização/recall e observabilidade.

## 7. Onde ainda NÃO é framework (honesto)

Pontos onde a fronteira hoje vaza — a fila de maturação para virar framework de fato:

- **Canal/transporte sem contrato único.** Web, Hermes e Meta cada um faz o *wiring*
  do `ChatFlowService` à mão (recall, session_state, stores). Falta um **contrato de
  canal** (um `ChannelTransport`/factory) para um canal novo entrar sem repetir
  fiação. Hoje é copy-paste gated.
- **Estado de sessão fragmentado.** Coexistem o store antigo do escape FSM e o
  `SessionStateStore` novo; o `SessionState` é anêmico e **ainda não tem reader**.
  Unificar (R2) é dívida aberta.
- **Slots de descoberta (vendas) sem namespace.** WS-4 layer 3 ainda não tem o
  namespace por-domínio que a R2 exige.
- **Identidade/cliente parcialmente domain-scoped.** `customer_ref` já é estável,
  mas a fronteira identidade↔domínio ainda não está fechada.

Estes não são bugs; são a **lista honesta** do que falar antes de chamar isto de
framework maduro.

## 8. Anti-padrões (o que NÃO fazer)

- **God-contract único** "que conhece todos os domínios". Framework = muitos seams
  estreitos + domínios-plugin, não um contrato gigante.
- Campo de **um** domínio no `SessionState`/contrato compartilhado.
- `if domain == "vendas"` (ou qualquer ramo por domínio) no core.
- **Pipeline serial** de persistência (RAM→Redis→off-box→PG em série) — vira a
  fronteira de durabilidade frágil que o plano rejeitou.
- Mover inteligência (handoff, confinamento, decisão) para a borda/transporte.
