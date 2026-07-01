# Persistência de conversa em camadas (RAM → Redis → sink off-box → Postgres noturno)

Status (2026-07-01): **Fases 0–4 implementadas; Fases 2–4 confirmadas vivas em
produção na VPS** (Redis instalado e `SESSION_STATE_BACKEND=redis`; batch noturno
rodando desde 2026-06-29 com 39 resumos gravados sem erro; `ENABLE_SUMMARY_RECALL=true`
agora também no canal Hermes/WhatsApp após deploy dos commits que faltavam). Falta
só a Fase 0 (sink off-box), bloqueada por credenciais R2. Ver detalhamento por fase
em `conversation-persistence-tiering-tech-plan.md`.
Origem: conversa com Silotto (TekZoom HG) indicando **milhares de pedidos de
suporte por dia**. Dono atual da frente: Renan (persistência e VPS passaram a ser
nossas — ver `team-ownership-change`).

Este documento **evolui** a direção fechada em `docs/architecture/conversation-archive-sink.md`
e na memória de projeto; ele não a substitui sem dizer o que mudou (ver
"Reconciliação" abaixo). Leia antes: `docs/architecture/architecture.md` (seção
`app/conversations`), `docs/architecture/conversation-archive-sink.md`,
`docs/architecture/cost-latency-profile.md`, `docs/architecture/observability.md`.

---

## 1. Decisão (o desenho proposto)

Quatro camadas de persistência, do mais quente ao mais frio, mais uma máquina de
estados de sessão e um batch noturno de sumarização:

| Camada | Janela | Papel | Latência alvo |
| --- | --- | --- | --- |
| **Hot** (RAM/cache) | ~45 min | turno corrente + estado da sessão para resposta rápida | mínima |
| **Operacional** (Redis + AOF) | ~7 dias | mensagens e tickets em aberto; janela de trabalho do suporte | baixa/média |
| **Seguro off-box** (append-only sink) | enquanto o turno existir | cópia durável fora da VPS contra crash/restart/deploy | fora do hot path |
| **Warehouse** (Postgres) | longo prazo | base analítica e RAG, **alimentada por batch noturno** | irrelevante (offline) |

- **Máquina de estados no Redis:** por `session_id` (hash, nunca cru) guardamos
  `{ state, domain, confidence, ... }` com TTL. Se o turno cai do hot para o
  operacional, o código sabe em que pé está a interação sem reprocessar histórico.
- **Sumarização noturna (3h):** ao promover o dia do Redis para o Postgres, não
  gravar a conversa crua palavra por palavra. Um modelo barato (`gpt-4o-mini`, já
  o cavalo de batalha do projeto) lê a conversa, extrai problema/solução/status e
  grava um registro estruturado e sanitizado. Na próxima vez que o mesmo cliente
  abrir ticket, o RAG busca o **resumo** em vez de reler 50 mensagens — economiza
  tokens e latência.

---

## 2. Mapa: cada camada → primitiva que já existe

Boa parte disto **não é código novo**; é nomear e ligar o que já está no repo.

| Camada proposta | Já existe? | Onde |
| --- | --- | --- |
| Hot RAM + estado de sessão | **não** (a construir) | seam novo `SessionStateStore` |
| Operacional 7d (Redis+AOF) | **não** (a construir) | adapter Redis atrás do mesmo seam |
| Seguro off-box append-only | **sim, implementado** | `ENABLE_CONVERSATION_ARCHIVE`, `ConversationArchiveSink`, `S3ObjectSink` (`app/conversations/archive_sink.py`), alimentado pelo `operational_outbox` |
| Warehouse Postgres | **sim, parcial** | `PERSISTENCE_BACKEND=postgres`, `ConversationHistoryService`, tabelas `conversations`/`messages` |
| Batch noturno de sumarização | **não** (a construir) | job + contrato de registro estruturado |
| Disciplina anti-PII (hash de sessão, redação, sanitização) | **sim** | `hash_session`, `sanitize_payload`, `redaction_version` |

O ponto importante: **o "meio campo 2 fora do server" que você descreveu já está
pronto** (append-only sink com destino S3, default desligado). Ele é a rede de
segurança contra perda. O trabalho novo é o tier quente (RAM/Redis + estado) e o
batch de sumarização.

---

## 3. Reconciliação com a direção anterior (não varrer para baixo do tapete)

A direção convergida em 2026-06-26 **rejeitou explicitamente** "persistência em
RAM/tier-médio com flush diário", porque um flush só diário perde até ~1 dia num
restart. O desenho atual reintroduz RAM + tier médio + flush noturno. Isso **só é
seguro** por causa de uma diferença concreta:

- Antes (rejeitado): RAM → flush **diário** para o store, **sem** cópia durável
  incremental no meio. A fronteira de durabilidade era o flush diário → perda de
  até 1 dia.
- Agora (aceitável): RAM/Redis → **cópia durável quase-real-time** via outbox →
  append-only sink off-box. O flush noturno para o Postgres deixa de ser a
  fronteira de durabilidade; vira apenas a **consolidação analítica**.

Regra que mantém isto honesto: **o batch noturno nunca pode ser a única cópia
durável de um turno.** Todo turno reconhecido tem que estar, antes da madrugada,
ou no sink off-box ou no Postgres write-through. O frase-chave da decisão antiga
continua valendo: *o que mata perda é frequência de escrita incremental, não o
lugar do store.*

---

## 4. Fronteira de durabilidade (a decisão que precisa ficar explícita)

Há duas formas de encaixar o Postgres, e elas mudam o RPO. **Recomendação: A.**

- **A — Postgres write-through continua sendo fonte da verdade dos turnos; Redis é
  cache/estado por cima (recomendado).** Mantém `ConversationHistoryService` como
  está. Redis acelera leitura de histórico e guarda a máquina de estados; o batch
  noturno só *sumariza* o que já está durável. RPO ≈ o do write-through +
  sink. Menos risco, reaproveita o que existe.
- **B — Redis AOF vira a fonte da verdade operacional; Postgres recebe só resumos
  noturnos.** É o desenho mais "puro" do que foi proposto, mas move a durabilidade
  para `appendfsync everysec` (perde ≤1s no crash do processo Redis) + sink
  off-box. Exige operar Redis com AOF como dado crítico (não como cache
  descartável) e tratar a perda da janela operacional crua como aceitável depois
  da sumarização.

No volume informado (milhares/dia ≈ poucos req/s no pico), **o Postgres
write-through não é gargalo** — então a opção A entrega quase todo o benefício de
latência (via cache de leitura + estado no Redis) sem abrir mão da fonte da verdade
transacional. B só se justifica se aparecer evidência de que o write-through
incremental no hot path está custando latência percebida, o que hoje **não** é o
caso (`docs/architecture/cost-latency-profile.md`: orquestração soma single-digit de ms; quase
toda a latência é o round-trip do modelo).

### Decisão fechada (2026-06-29): **A**, com escada incremental para as ideias da B

Avaliamos um desenho alternativo (Renan): RAM 45m → Redis 7d como **verdade
operacional** → snapshot off-box → Postgres só de madrugada. É a Opção B com um hot
tier na frente. Onde a B/Renan **falha no nosso cenário** e a A não:

- **Backup por snapshot periódico do Redis** perde tudo desde o último snapshot se a
  VPS inteira morrer (AOF não salva se a máquina sumiu). A A faz **append por-turno
  off-box via outbox** (perda ≈ segundos).
- **Madrugada como fronteira de durabilidade** já foi rejeitada (ver §3); a B reintroduz
  isso para os turnos não-resolvidos do dia.
- **Carga operacional**: a B transforma o Redis em dado crítico (AOF + snapshot +
  eviction segura + restore + reconciliação noturna) — superfície demais para um time
  de dois. A A reaproveita write-through + outbox + sink que **já existem**.

Onde a B é genuinamente melhor (e por isso vira *escalada futura*, não descarte):
aceitar writes com **Postgres fora** e **vazão em concorrência altíssima** — nenhum
dos dois é a restrição de hoje (milhares/**dia**, não milhares **simultâneos**).

**Regra de ouro (vale em toda escala): o que é síncrono é a âncora de durabilidade;
o backup off-box é sempre append por-turno — nunca snapshot/flush diário como
fronteira de durabilidade.**

Escada de escalada (só sobe quando o gatilho aparecer, sem virar a B inteira):

| Nível | Gatilho que justifica | O que liga (flag) | Vem da ideia |
| --- | --- | --- | --- |
| **0 (agora)** | — | Postgres write-through (âncora) + outbox (R2 por-turno + fan-out) + estado quente in-memory fail-open + resumo noturno | A |
| **1** | restart/multi-worker perde estado de sessão | `RedisSessionStateStore` (estado quente em Redis, TTL, **não-autoritativo**, fail-open) | "RAM 45m / Redis 7d" da B |
| **2** | leitura de histórico/triagem de tickets-em-aberto vira gargalo | cache de leitura 7d no Redis por cima do Postgres | "meio campo" operacional da B |
| **3** | write-through vira gargalo **ou** requisito de aceitar com Postgres fora | promover **localmente** (só no domínio que provar) o caminho para Redis-first (Opção B) | âncora-Redis da B, localizada e por evidência |

Assim a A **cresce para dentro da B** de forma incremental e reversível, em vez de
pagar a complexidade adiantado por uma carga que ainda não existe.

### Fluxos de referência (síncrono vs assíncrono)

O princípio operacional do Nível 0, concreto. Existe um diagrama de referência
deste desenho (gerado na discussão de 2026-06-29); o texto abaixo é a fonte da
verdade.

**Fluxo de um turno (qualquer domínio):**

1. Inbound (web/WhatsApp/…) chega ao `ChatFlowService` — roteia, recupera (pgvector),
   responde (LLM).
2. **Síncrono (1 transação Postgres):** grava o turno (`conversations`/`messages` +
   `chat_audits`) **e**, na mesma transação, **enfileira o(s) evento(s) no
   `operational_outbox`**. Commit atômico = o turno está durável e a cópia está
   garantida. Custo ~ms (não percebido; o LLM domina).
3. **Estado quente (síncrono, fail-open):** lê/grava `SessionStateStore` (in-memory
   no Nível 0) por `(domain, channel, session_hash)`. Se o store cair, o `/chat`
   responde mesmo assim — não é autoritativo.
4. **Assíncrono (worker `dispatch_outbox`, fora do hot path):** entrega o evento
   `conversation.turn.archived` ao **backup off-box (R2/S3, append-only)** — at-least-once,
   idempotente. RPO ≈ lag do worker (segundos).

**Fluxo de handoff (escalou para humano):**

1. Mesma transação síncrona do turno, **mais** o `support_cases` (ticket durável) +
   o evento `handoff.requested` no outbox. **Este é o gate de consistência:** se a
   transação falhar, **não** se promete humano ao usuário (não "barra" em falso).
2. Assíncrono via outbox: entrega de `handoff.requested` ao consumidor externo
   (quando configurado) + a cópia off-box. O **support inbox** (leitura) já serve o
   ticket a partir do Postgres, independente da entrega externa.

**Onde o Redis entra (Níveis 1–2, sob gatilho):** como backend do `SessionStateStore`
(estado quente, TTL, não-autoritativo) e/ou cache de leitura 7d por cima do Postgres
— **nunca** como âncora de durabilidade no Nível 0.

---

## 5. Tradeoffs honestos / limites de MVP

Alinhado a `docs/product-positioning.md` (comercial-técnico, honesto sobre limites):

1. **"Milhares/dia" não é alto volume.** ~poucos req/s no pico. Redis aqui é
   escolha de **latência e ergonomia** (estado com TTL, janela operacional de 7d),
   **não** necessidade de throughput. Vale dizer isso em voz alta: o ganho é UX e
   estado, não "aguentar a carga" — o Postgres aguentaria.
2. **Mais um serviço stateful na VPS.** Redis com AOF crítico = backup, monitoração
   de memória, política de `maxmemory`/eviction que **não** pode despejar dado
   ainda não sumarizado, e recuperação testada. Adiciona superfície operacional.
   Ver `vps-runtime-topology`.
3. **"RAM" literal não sobrevive a multi-worker.** Cache em memória de processo é
   por-worker no uvicorn e some no restart. O tier de 45 min deve ser **Redis com
   TTL curto**, não memória de processo, ou o estado fica inconsistente entre
   workers. "RAM" no diagrama = camada lógica quente, implementada no Redis.
4. **PII nos resumos.** `[Cliente]: João / [Problema]: ... / [Solução]: ...` é dado
   de cliente. O projeto **nunca** persiste `session_id` cru e sempre sanitiza
   (`redaction_version`). O registro estruturado tem que passar pela mesma
   disciplina: identificar cliente por id/hash estável, redigir PAN/segredos/PII do
   texto **antes** de mandar pro modelo de sumarização e antes de gravar. O resumo
   não pode reintroduzir dado que o hot path já redigiu.
5. **Custo da sumarização noturna.** `gpt-4o-mini` a ~US$0,0004–0,0005/chamada.
   Mesmo com milhares de conversas/dia, ordem de poucos dólares/dia — barato, mas
   não-zero e cresce com volume. Sumarizar **por conversa fechada**, não por
   mensagem, e pular conversas triviais (1 turno, resolvidas por atalho) corta a
   conta. Métrica de custo deve entrar no `docs/architecture/cost-latency-profile.md`.
6. **Qualidade do resumo é aposta de retrieval.** Um resumo errado polui o RAG para
   o próximo ticket do mesmo cliente. Precisa de eval: amostrar resumos e conferir
   problema/solução/status contra a conversa real antes de confiar no caminho.

---

## 6. Contrato — máquina de estados de sessão (`SessionStateStore`)

Seam novo, mesma filosofia do `ConversationArchiveSink`: interface estável,
implementação trocável, default seguro.

```python
class SessionStateStore(Protocol):
    def get(self, *, domain: str, channel: str, session_hash: str) -> SessionState | None: ...
    def put(self, *, domain: str, channel: str, session_hash: str,
            state: SessionState, ttl_seconds: int) -> None: ...
    def clear(self, *, domain: str, channel: str, session_hash: str) -> None: ...
```

`SessionState` (sanitizado, sem `session_id` cru, sem PII livre):
`{ state: str, domain: str, confidence: float, turn_id, redaction_version, updated_at }`.

- **Default:** `InMemorySessionStateStore` (single-process; serve local/CI/testes,
  igual ao papel do `AppendOnlyFileSink`).
- **Operacional:** `RedisSessionStateStore` (TTL 45 min refrescado a cada atividade;
  AOF dá a janela de 7d). Atrás de flag, ex. `SESSION_STATE_BACKEND=redis`.
- Chave isolada por `domain`/`channel`/`session_hash` — mesma regra de isolamento
  de `ConversationHistoryService`. Nunca a chave crua.

---

## 7. Contrato — registro estruturado do batch noturno

Saída da sumarização, gravada no Postgres como warehouse:

```json
{
  "domain": "suporte-vps-whatsapp",
  "customer_ref": "<id/hash estável, nunca cru>",
  "problem": "DNS nao propagava na VPS",
  "solution": "Ajustado nameservers para ns1/ns2 do provedor",
  "status": "resolvido | em_aberto | escalado",
  "source_turn_count": 12,
  "redaction_version": "<versao>",
  "summarized_at": "<ts>",
  "model": "gpt-4o-mini"
}
```

Garantias: idempotente por conversa (reexecução do batch sobrescreve o mesmo
registro), texto já redigido antes de ir ao modelo, e o registro carrega
`redaction_version` para auditoria. Indexável pelo RAG por `customer_ref` + domínio.

---

## 8. Plano de execução em fatias (menor passo seguro primeiro)

Cada fatia entra atrás de flag, com default desligado e testes, sem tocar latência
do `/chat`.

1. **Operacionalizar o que já existe.** Ligar o append-only sink off-box em staging
   (bucket S3 + worker `dispatch_outbox --loop` no systemd) — fecha o gap de perda
   **antes** de qualquer Redis. Já documentado em `docs/architecture/conversation-archive-sink.md`.
2. **`SessionStateStore` seam + impl in-memory + testes.** Sem Redis ainda. Liga o
   `ChatFlowService` para ler/escrever estado por um caminho desligável.
3. **`RedisSessionStateStore`** atrás de flag, com TTL e fallback para in-memory se
   o Redis cair (falhar aberto, igual ao histórico). Runbook de operação do Redis
   na VPS (AOF, maxmemory, backup).
4. **Cache de leitura de histórico no Redis** (opcional, só se a latência justificar
   — hoje não justifica; manter Postgres write-through como SoT — opção A).
5. **Batch noturno de sumarização** como script operacional (`scripts/`), idempotente,
   sumariza conversas fechadas, sanitiza antes do modelo, grava o contrato da §7.
   Agendado por systemd timer (3h), não por cron dentro do app.
6. **Eval de qualidade do resumo** + métrica de custo no `cost-latency-profile`.

Começar pela fatia 1 ou 2: a 1 não tem código novo (só deploy) e remove risco real
de perda já; a 2 é o menor incremento de código com seam testável.

---

## 9. Validação esperada

- `python -m pytest` e `python -m compileall app tests scripts` em toda fatia.
- Testes unitários por seam novo (estado in-memory, estado Redis com fake, batch de
  sumarização com modelo mock) — espelhando `tests/test_conversation_archive_sink.py`.
- Integração gated (Postgres real, harness #84) para o caminho warehouse.
- `python -m app.evals.run_domain_eval suporte-vps-whatsapp` quando o resumo entrar
  no caminho de RAG.
- Nenhum log de PII/`session_id` cru — checagem de privacidade em `docs/architecture/observability.md`.

---

## 10. Fronteiras de ownership

Persistência e runtime são do Renan agora (`team-ownership-change`). Ainda assim
manter o estilo seam/adapter+contrato — é boa arquitetura, não só cortesia: cada
backend (in-memory, Redis, S3) trocável por flag, sem mudar chamador nem schema.

## 11. Decisões em aberto

- ~~Opção **A vs B** da §4~~ **RESOLVIDA (2026-06-29): A**, com escada de escalada
  incremental para absorver as ideias da B sob gatilho (ver §4, "Decisão fechada").
- Retenção exata de cada camada (45 min / 7 d são pontos de partida, não lei).
- Política de `maxmemory`/eviction do Redis que **não** descarte turno não
  sumarizado. **Confirmado em produção (2026-07-01)**: `maxmemory 256mb`,
  `maxmemory-policy volatile-ttl`, `appendonly yes`/`appendfsync everysec`.
- Quais conversas pular na sumarização (triviais/atalho) para conter custo.
- ~~Achado (2026-07-01): `ENABLE_SUMMARY_RECALL` ligado sem amostragem de
  qualidade registrada~~ **RESOLVIDO (2026-07-01, retroativo)**: amostragem feita
  sobre os 39 resumos existentes — 0 achados de PII/PAN (varredura automática +
  leitura manual de 8 casos), problema/solução batem com a conversa real em 7/8.
  Limitação documentada: conversas longas/multi-assunto retêm só o último tópico
  no resumo (ver tech-plan §Fase 4). Recall segue ligado; falta o caso de eval no
  domínio e a métrica de custo.
