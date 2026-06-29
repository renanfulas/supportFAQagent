# Plano técnico — persistência de conversa em camadas

Plano de execução detalhado, em nível de arquivo/classe/flag, para implementar a
decisão registrada em
[`conversation-persistence-tiering-plan.md`](./conversation-persistence-tiering-plan.md).
Este documento é o "como"; o outro é o "o quê / por quê".

Princípios herdados do projeto (não negociar):
- Cada backend entra atrás de **flag com default seguro**, espelhando o seam do
  `ConversationArchiveSink` (`app/conversations/archive_sink.py`).
- **Nunca** persistir `session_id` cru nem PII livre; reusar `hash_session`,
  `sanitize_payload`, `redaction_version`.
- Nada novo no **hot path** do `/chat` sem flag desligável e com *fail-open*.
- Migrations **forward-only** com ledger (`python -m scripts.migrate`). A `011` já
  está aplicada (em prod inclusive); `010` é um gap de numeração não usado. Para não
  aplicar fora de ordem, a próxima migration nova é a **`012_`**.
- `python -m pytest` + `python -m compileall app tests scripts` em toda fatia.

Recomendação de durabilidade desta frente: **opção A** do plano de decisão —
Postgres write-through (`ConversationHistoryService`) continua fonte da verdade dos
turnos; Redis é cache/estado por cima. As fases abaixo respeitam isso.

---

## Fase 0 — Operacionalizar o sink off-box (sem código novo)

Status (2026-06-29): **prep feita, bloqueada só por credenciais R2.** Na VPS o
`boto3` já está no `.venv` e o worker systemd `supportfaq-outbox.service` existe
dormente (disabled/inactive); a outbox está limpa. Falta só o destino R2
(bucket + endpoint + Access Key/Secret) para ligar as flags abaixo e o worker.

Fecha o gap de perda **antes** de qualquer Redis. Já documentado em
`docs/conversation-archive-sink.md`; aqui só o checklist de execução.

- VPS `.env`: `PERSISTENCE_BACKEND=postgres`, `ENABLE_CONVERSATION_ARCHIVE=true`,
  `OUTBOX_CONVERSATION_ARCHIVE_TRANSPORT=append_only_sink`,
  `CONVERSATION_ARCHIVE_SINK_TRANSPORT=s3` + bucket/região/credenciais.
- `pip install '.[s3]'` no `.venv` do serviço.
- Worker systemd dedicado: `python -m scripts.dispatch_outbox --loop`,
  `Restart=always`, separado do `supportfaq.service` (ver `vps-runtime-topology`).
- **Aceite:** turno persistido aparece como objeto no bucket; matar o app entre o
  commit e o dispatch não perde o turno (o outbox reentrega).

Sem mudança de código. Fases 1–4 são as entregas de engenharia.

---

## Fase 1 — `SessionStateStore` seam + impl in-memory

Status: **implementada (2026-06-29)**, default no-op. O seam ficou em
`app/conversations/session_state.py` (`SessionState` + `SessionStateStore` Protocol +
`InMemorySessionStateStore` com TTL + `build_session_state_store_from_env`). Config:
`SESSION_STATE_BACKEND` (memory|redis) + `SESSION_STATE_TTL_SECONDS` (2700). O
`ChatFlowService` grava o estado via wrapper `answer()`→`_answer_inner()` +
`_record_session_state` (fail-open, chaveado por `hash_session`), e `chat.py`/`web_chat.py`
injetam o store de `app.state.chat_session_state_store` só quando
`persistence_backend==postgres`. Cobertura em `tests/test_session_state_store.py`.
Pendente (próximas fatias): o **leitor** do estado (consumo), o backend Redis
(Nível 1), e migrar o estado de escape do transporte Hermes para o mesmo seam.

Menor incremento de código. Sem Redis, sem infra.

### Arquivos
- **Novo** `app/conversations/session_state.py`:

```python
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Protocol, runtime_checkable
import os, threading, time

SUPPORTED_SESSION_STATE_BACKENDS = {"memory", "redis"}

@dataclass(frozen=True)
class SessionState:
    state: str
    domain: str
    confidence: float
    turn_id: str | None
    redaction_version: str
    updated_at: float

@runtime_checkable
class SessionStateStore(Protocol):
    def get(self, *, domain: str, channel: str, session_hash: str) -> SessionState | None: ...
    def put(self, *, domain: str, channel: str, session_hash: str,
            state: SessionState, ttl_seconds: int) -> None: ...
    def clear(self, *, domain: str, channel: str, session_hash: str) -> None: ...

class InMemorySessionStateStore:
    """Single-process store with TTL. Local/CI/test default — mirrors the role of
    AppendOnlyFileSink. NOT safe across uvicorn workers (see tech-plan §risks)."""
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, SessionState]] = {}
        self._lock = threading.Lock()
    # _key = f"{domain}::{channel}::{session_hash}", expira por wall-clock no get

def build_session_state_store_from_env() -> SessionStateStore:
    backend = (os.getenv("SESSION_STATE_BACKEND", "memory").strip().lower() or "memory")
    if backend not in SUPPORTED_SESSION_STATE_BACKENDS:
        raise ValueError(f"unsupported session state backend: {backend}")
    if backend == "memory":
        return InMemorySessionStateStore()
    if backend == "redis":
        from app.conversations.session_state_redis import RedisSessionStateStore
        return RedisSessionStateStore.from_env()   # Fase 2
    raise ValueError(backend)
```

- **Modificar** `app/core/config.py`: novos campos espelhando o padrão `Field(...)`:
  - `session_state_backend: str = Field(default="memory", alias="SESSION_STATE_BACKEND")`
  - `session_state_ttl_seconds: int = Field(default=2700, alias="SESSION_STATE_TTL_SECONDS")` (45 min)
  - validar `session_state_backend in {"memory","redis"}` no mesmo bloco que hoje
    valida `persistence_backend` (config.py:332).
- **Modificar** `app/orchestration/chat_flow.py`: injetar no construtor, igual ao
  `history_service` (chat_flow.py:31-39):
  ```python
  def __init__(self, *, history_service=None, session_state_store: SessionStateStore | None = None):
      ...
      self.session_state_store = session_state_store
  ```
  Ler o estado no início de `answer()` e gravar antes de retornar (estado =
  `confidence`, `domain`, e um rótulo derivado: `blocked`/`answered`/`no_context`/
  `escalated`). **Tudo guardado por `session_hash`**, computado com o mesmo
  `hash_session` que o `ConversationHistoryService` (service.py:43). Nunca o
  `session_id` cru. Sem store injetado → no-op (default desligado de fato).
- **Modificar** os pontos de construção do `ChatFlowService`
  (`app/api/routes/chat.py`, `app/api/routes/web_chat.py`) para passar
  `build_session_state_store_from_env()` quando `persistence_backend == "postgres"`;
  caso contrário `None`.

### Testes
- **Novo** `tests/test_session_state_store.py`, espelhando
  `tests/test_conversation_archive_sink.py`: TTL expira; isolamento por
  domain/channel/hash; `build_..._from_env` roteia memory/redis e rejeita backend
  inválido; `ChatFlowService` lê/grava estado e vira no-op sem store.

### Aceite
- `/chat` idêntico com `SESSION_STATE_BACKEND` ausente (no-op).
- Estado recuperável dentro do TTL por `(domain, channel, session_hash)`.
- Zero `session_id` cru em qualquer chave ou log.

---

## Fase 2 — `RedisSessionStateStore` (operacional, 7d via AOF)

### Arquivos
- **Novo** `app/conversations/session_state_redis.py`:
  - `RedisSessionStateStore` satisfaz `SessionStateStore`.
  - `from_env()`: lê `SESSION_STATE_REDIS_URL`; cliente `redis-py` injetável (igual
    `S3ObjectSink` aceita `client=` para teste).
  - `put` usa `SET key value EX ttl_seconds` (TTL = camada quente de 45 min,
    refrescado a cada atividade); valor = JSON sanitizado de `SessionState`.
  - `get` desserializa; **fail-open**: em `RedisError`, logar evento e retornar
    `None` (mesma filosofia de `load_recent`, service.py:59) — Redis fora não
    derruba `/chat`.
  - Chave: `sess:{domain}:{channel}:{session_hash}`.
- **Modificar** `pyproject.toml`: extra opcional `redis` (como o extra `s3`).
  Rodar `python -m pip check` e `python -m pip_audit .`.
- **Modificar** `app/health/` (readiness): incluir ping opcional ao Redis em
  `/health/ready` quando `SESSION_STATE_BACKEND=redis` (não-fatal para liveness).

### Operação (runbook novo `docs/runbooks/redis-session-state.md`)
- `appendonly yes`, `appendfsync everysec` (perde ≤1s no crash do processo).
- `maxmemory` + `maxmemory-policy volatile-ttl` — **só** despeja chaves com TTL;
  nunca dado ainda não consolidado no warehouse (a consolidação é a Fase 3).
- Backup do AOF e restore testado; serviço systemd; bind em loopback/rede interna,
  `requirepass`. Ownership runtime = Renan (`team-ownership-change`).

### Testes
- Reusar `tests/test_session_state_store.py` com um **fake redis** (cliente
  injetado), incluindo o caminho `RedisError → fail-open → None`.

### Aceite
- Com Redis up: estado sobrevive a restart do app (não do Redis) dentro do TTL.
- Com Redis down: `/chat` responde normal (fail-open), readiness sinaliza degradado.

---

## Fase 3 — Warehouse + batch noturno de sumarização

Postgres como base analítica/RAG, alimentada por batch idempotente às ~3h.

### Migration
- **Novo** `migrations/012_conversation_summaries.sql` (forward-only, ledger):
  ```sql
  CREATE TABLE conversation_summaries (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain          TEXT NOT NULL,
    customer_ref    TEXT NOT NULL,           -- id/hash estável, NUNCA cru
    problem         TEXT NOT NULL,
    solution        TEXT NOT NULL,
    status          TEXT NOT NULL,           -- resolvido|em_aberto|escalado
    source_turn_count INT NOT NULL,
    redaction_version TEXT NOT NULL,
    model           TEXT NOT NULL,
    summarized_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    conversation_key TEXT NOT NULL,          -- idempotência do batch
    UNIQUE (domain, conversation_key)
  );
  CREATE INDEX ix_conv_summaries_lookup ON conversation_summaries (domain, customer_ref);
  ```
  Isolamento por `domain` obrigatório (igual ao schema central, `architecture.md`).

### Script
- **Novo** `scripts/summarize_conversations.py` (espelha o estilo de
  `scripts/dispatch_outbox.py`: lê env, conecta com timeouts, idempotente):
  - Seleciona conversas **fechadas** do dia (janela `--since/--until`) das tabelas
    `conversations`/`messages`.
  - **Pula triviais** (1 turno, resolvidas por atalho/checkout/bloqueio) para
    conter custo (decisão aberta §11 do plano de decisão).
  - Para cada conversa: **sanitiza/redige o texto** (`sanitize_payload`,
    detector de PAN `contains_card_number`/`app/core/persistence_sanitize.py`)
    **antes** de montar o prompt do sumarizador.
  - Chama `LLMService`/`LLMWrapper` com `gpt-4o-mini`, `temperature=0.0`,
    pedindo JSON estruturado (problem/solution/status). Reusa o provider isolado
    em `app/llm/` — não cria caminho de LLM paralelo.
  - `UPSERT ... ON CONFLICT (domain, conversation_key)` → reexecução sobrescreve o
    mesmo registro (idempotente).
  - Logs sem PII (`docs/observability.md`); métrica de custo/contagem em stderr JSON.
- Flag de ativação: `ENABLE_CONVERSATION_SUMMARY=false` por default.

### Agendamento
- systemd **timer** `summarize-conversations.timer` (3h America/Sao_Paulo), não cron
  dentro do app. Runbook em `docs/runbooks/conversation-summary-batch.md`.

### RAG (consumo)
- `app/retrieval/` ganha uma fonte opcional que, dado `(domain, customer_ref)`,
  injeta o resumo estruturado mais recente como contexto — **atrás de flag**, só
  depois do eval de qualidade (Fase 4). Não muda o contrato `VectorStore`; entra
  como contexto adicional no `build_prompt`, marcado como dado não confiável.

### Testes
- **Novo** `tests/test_conversation_summary.py`: provider **mock**, asserta JSON
  estruturado, idempotência do upsert, *skip* de triviais, e que **PAN/PII é
  redigido antes** de ir ao modelo (caso com cartão → não vaza).
- Integração gated (Postgres real, harness #84) para o caminho de escrita do
  warehouse, espelhando `tests/integration/test_phase0_postgres.py`.

### Aceite
- Batch é idempotente (rodar 2x = mesmo estado).
- Nenhum resumo contém PAN/segredo/`session_id` cru.
- Custo por execução logado e proporcional a conversas não-triviais.

---

## Fase 4 — Eval de qualidade do resumo + custo

- Amostragem de resumos conferida contra a conversa real (problema/solução/status).
- Caso de eval no domínio (`domains/suporte-vps-whatsapp/evals/`) que valida que o
  resumo recuperado melhora — e não polui — a próxima resposta.
- Métrica de custo da sumarização adicionada a `docs/cost-latency-profile.md`.
- Só depois disso ligar o consumo do resumo no RAG em staging.

---

## Ordem, flags e estado default

| Fase | Entrega | Flag principal | Default |
| --- | --- | --- | --- |
| 0 | Sink off-box em staging | `ENABLE_CONVERSATION_ARCHIVE` | off |
| 1 | Seam de estado + in-memory | `SESSION_STATE_BACKEND` | `memory` (no-op no chat) |
| 2 | Estado no Redis + AOF | `SESSION_STATE_BACKEND=redis` | off |
| 3 | Warehouse + batch noturno | `ENABLE_CONVERSATION_SUMMARY` | off |
| 4 | Eval + consumo no RAG | flag de retrieval do resumo | off |

Tudo *dark* por default: a `main` continua se comportando como hoje até cada flag
ser ligada conscientemente em staging/produção.

## Riscos técnicos a vigiar
- **Multi-worker:** in-memory é por-worker; produção multi-worker exige Redis
  (Fase 2) para estado consistente. Documentar para não confiar no in-memory fora
  de single-process.
- **Eviction do Redis** não pode descartar dado não consolidado — daí
  `volatile-ttl` + consolidação write-through (opção A) em vez de depender do AOF
  como única fonte.
- **Qualidade do resumo** polui RAG se errado — gate de eval (Fase 4) é
  pré-requisito para o consumo, não opcional.

## Validação por fase
- Toda fase: `python -m pytest`, `python -m compileall app tests scripts`.
- Fase 2: `python -m pip check`, `python -m pip_audit .` (mudou `pyproject.toml`).
- Fase 3–4: `python -m app.evals.run_domain_eval suporte-vps-whatsapp`.
- Migrations: `python -m scripts.migrate` em banco de teste; nunca aplicar fora do
  runner com ledger.
