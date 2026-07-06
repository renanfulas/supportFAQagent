# Plano Tecnico - Console Do Time De Suporte (Tickets E Metricas)

Status: proposto em 2026-07-02, revisado em 2026-07-02 apos review de hardening
(staff em tabela propria, sessao diaria, OTP staff dedicado, SLA calculado em
Python com relogio unico do banco, dono do caso visivel na fila). Fluxo de
login refinado em 2026-07-02: lembrete de dispositivo (1 clique no dia a dia)
e expiracao fixa as 4h da manha no fuso do time.
**Fase A implementada em 2026-07-03** (migration 014, `app/support/sla.py`,
`app/support/staff_auth.py`, fachada `/web/support/*`, `manage_staff.py`,
readiness + schema contract, testes verdes; contrato registrado em
`docs/architecture/integration-contracts.md`, smoke em
`docs/runbooks/support-console-smoke.md`).
**Fase B implementada em 2026-07-03** (migration 015 —
`assignee_staff_id` + `support_case_events` —, `app/support/transitions.py`
com compare-and-swap e evento auditavel na mesma transacao, `waiting_seconds`
real plugado em `compute_sla`, filtro `assignee=me`, historico de eventos no
detalhe, endpoint `POST /web/support/cases/{case_id}/transition` com CSRF por
`X-Requested-With`; testes unitarios + integracao postgres opt-in com
concorrencia real).
**Fase C implementada em 2026-07-03** (`app/support/metrics.py`: `backlog`
reusando `compute_sla` sobre o conjunto ativo — uma fonte de verdade so —,
`throughput` diario zero-fillado no fuso do time, `escalation_reasons` via
`jsonb_array_elements_text`, `feedback` com `helpful_rate` e
`unknown_domain_count` a partir do join `feedback -> chat_audits`,
`response_times` via medianas `percentile_cont`; endpoint
`GET /web/support/metrics` + schema; testes com fixtures deterministicas).
**Smoke em staging confirmado em 2026-07-06** (deploy real na VPS a partir de
`origin/main`, migrations 014-018 aplicadas, operador cadastrado via
`manage_staff.py`, flag `ENABLE_SUPPORT_CONSOLE=true`): dark-check 404,
login OTP real via WhatsApp, lembrete de dispositivo (1 clique) emitindo e
resolvendo corretamente, telefone nao-staff negado com resposta identica,
fila com semaforo e SLA reais sobre o backlog existente, detalhe de caso,
ciclo completo de transicao (`claim` -> `wait_customer` -> `resume` ->
`close`) com evento auditado, `assignee=me`, `GET /web/support/metrics` com
as quatro visoes populadas, `logout` preservando/removendo o lembrete
conforme `forget_device`, e caplog sem telefone/codigo/token. Falta so a UI
`/team` (Juliano).

**Bug encontrado e corrigido durante o smoke (2026-07-06):**
`DatabaseRuntime.transaction()` (`app/db/runtime.py`) convertia **qualquer**
excecao levantada dentro do `with runtime.transaction()` — inclusive
rejeicoes de regra de negocio como `InvalidTransition` e `CaseNotFound`
(`app/support/transitions.py`) — em `DatabaseUnavailableError` (503), porque
o `yield` do gerador fica dentro do mesmo `try/except Exception` que trata
falhas reais de pool/conexao. Na pratica, um segundo `claim` no mesmo caso
respondia `503 support_inbox_storage_unavailable` em vez do `409
invalid_transition` documentado no contrato — nunca pego pelos testes
unitarios porque eles usam `FakeRuntime` (nao exercita o `transaction()`
real). O mesmo padrao ja existia, sem uso pratico ainda notado, em
`promote_pending_consent` (`app/db/operational.py`): `ConsentCaseNotFound`
levantada dentro da transacao tambem virava 503 em vez do 404 esperado.
Corrigido com uma classe marcadora nova, `TransactionBusinessError`
(`app/core/errors.py`), que `DatabaseRuntime.transaction()` deixa propagar
sem converter; `InvalidTransition`, `CaseNotFound` e `ConsentCaseNotFound`
agora herdam dela. Teste de regressao novo em
`tests/test_phase0_operational_safety.py`
(`test_database_runtime_lets_business_errors_propagate_from_transaction`)
exercitando o `DatabaseRuntime.transaction()` real (nao fake) para cobrir
essa classe de bug. `pytest` completo e `compileall` verdes apos o fix;
aplicado ao vivo na VPS (patch cirurgico, fora do fluxo normal de deploy) e
retestado com sucesso antes do PR. Ver
[PR #132](https://github.com/renanfulas/supportFAQagent/pull/132).
**Hardening pos-entrega (2026-07-03)**: (1) evento `support_console_auth_denied`
no confirm falho e no guard 401 (visibilidade de acesso negado sem eco de
identificadores); (2) `pending_consent -> cancel` na matriz de transicoes,
valvula de escape para o ticket cujo cliente nunca confirma o consentimento;
(3) poda oportunista de `staff_login_hints` expirados no start (o TTL so vivia
no cookie — lembrete orfao nunca expirava no servidor); (4) router
`/web/support/*` montado so com a flag ligada (dark real: fora do OpenAPI com
flag off); (5) correcao de tipo em `_load_waiting_seconds` (`ANY(%s::uuid[])`
— `uuid = ANY(text[])` nao tem operador no Postgres); (6) teste de integracao
opt-in `tests/integration/test_support_console_postgres.py` cobrindo as
queries de leitura/metricas contra Postgres real.
Plano de produto: [support-team-console-plan.md](support-team-console-plan.md).

## Decisao Arquitetural

O console e uma **fachada web staff** sobre o support inbox existente. Nada de
canal paralelo de dados, nada de segredo no browser:

```text
Browser (ask-host-genius, area interna /team)
  -> /web/support/auth/*   (OTP WhatsApp dedicado -> staff_sessions)
  -> /web/support/*        (exige sessao staff valida)
  -> SupportCaseRepository / compute_sla / agregacoes
  -> support_cases + messages + feedback (leitura; escrita so na Fase B)

Integracoes servidor-servidor e break-glass operacional
  -> GET /support com X-API-Key  (intocado)
```

Reusos deliberados:

- **Primitivas de OTP**: `normalize_phone`, `_hmac_digest`, desafio com
  expiracao/tentativas/cooldown e o adapter de entrega WhatsApp ja existem em
  `app/web_auth/` e ficam identicos. O que muda e o **vinculo no confirm**:
  staff nunca vira linha em `customers`/`verified_identities`.
- **Dados**: `SupportCaseRepository` (migration 009) ja entrega lista e
  contexto completo (`build_case_context`).
- **Guard de transicao**: mesmo padrao compare-and-swap ja usado pelo consent
  gate (`UPDATE ... WHERE id = %s AND status = 'pending_consent'` em
  `app/db/operational.py`).
- **UI**: area interna no `ask-host-genius`, mesma origem, mesmos padroes do
  chat publico (cookie `HttpOnly`, sem CORS, sem chave no JS).

## Autenticacao Staff - OTP WhatsApp Dedicado

### Modelo de dados (migration 014, Fase A)

```sql
CREATE TABLE staff_members (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  phone_hash TEXT NOT NULL UNIQUE,      -- HMAC(identity_hash_secret, E.164)
  phone_last4 TEXT NOT NULL,
  display_name TEXT NOT NULL,           -- exibido na fila e na auditoria
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT staff_members_status_check CHECK (status IN ('active', 'disabled'))
);

CREATE TABLE staff_sessions (
  session_hash TEXT PRIMARY KEY,        -- HMAC do token; token bruto so no cookie
  staff_id UUID NOT NULL REFERENCES staff_members(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL       -- proxima 4h da manha no fuso do time
);
CREATE INDEX idx_staff_sessions_staff ON staff_sessions (staff_id);
CREATE INDEX idx_staff_sessions_expires ON staff_sessions (expires_at);

CREATE TABLE staff_login_hints (
  hint_hash TEXT PRIMARY KEY,           -- HMAC do token de lembrete; bruto so no cookie
  staff_id UUID NOT NULL REFERENCES staff_members(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_used_at TIMESTAMPTZ
);
CREATE INDEX idx_staff_login_hints_staff ON staff_login_hints (staff_id);
```

Decisoes:

- **Staff nao e cliente.** Autenticacao staff escreve somente nestas tabelas.
  Metricas e fluxos de cliente (`customers`, `verified_identities`, consent
  gate) ficam livres de contaminacao.
- **`display_name` resolve a auditoria legivel** (fila mostra "Renan", nao um
  hash) e o mapeamento hash -> nome sem configuracao paralela.
- **Sessao diaria de verdade**: `expires_at` = proxima 4h da manha no fuso
  `SUPPORT_CONSOLE_TIMEZONE`, sem renovacao deslizante. Todo dia comeca com
  login novo e a sessao nunca morre no meio do expediente (um `+24h` corrido
  mataria a sessao de quem logou as 18h no meio da tarde seguinte).
- **Lembrete de dispositivo**: apos login bem-sucedido, um segundo cookie
  opaco de longa duracao habilita o botao "Entrar como <nome>" — o dia a dia
  vira 1 clique + codigo, sem digitar telefone. O lembrete **nao autentica**:
  sozinho, so dispara OTP para o WhatsApp do proprio operador.
- **Refinamento da implementacao (2026-07-03)**: o banco nao guarda telefone
  bruto, mas a entrega do OTP no fluxo de 1 clique precisa do numero. O cookie
  de lembrete carrega `<token>.<E.164>` (HttpOnly, `Path=/web/support/auth`):
  no start, o telefone do cookie so e aceito se o token resolver em
  `staff_login_hints` **e** o HMAC do telefone bater com o `phone_hash` do
  staff dono do token. Adulterar o telefone quebra o vinculo e o lembrete e
  ignorado; roubo do cookie continua so disparando OTP para o numero
  registrado do operador. O cookie e rotacionado a cada login. O cooldown de
  reenvio virou limiter uniforme por telefone (staff e nao-staff respondem
  identico, sem oraculo de enumeracao via 429).

### Fluxo

```text
Primeiro acesso no dispositivo:
1. Abre /team -> sem sessao e sem lembrete -> digita o proprio telefone
2. POST /web/support/auth/start -> codigo chega no WhatsApp
3. Digita os 6 digitos no desktop -> POST /web/support/auth/confirm
4. Sessao ativa ate as 4h + cookie de lembrete do dispositivo

Dia a dia (1 clique):
1. Abre /team -> botao "Entrar como <nome>" (lembrete presente)
2. POST /web/support/auth/start sem telefone -> codigo chega no WhatsApp
3. Digita os 6 digitos -> sessao ativa ate as 4h
```

### Endpoints

`POST /web/support/auth/start` — body `{ "phone": "+55..." }` (opcional quando
o cookie de lembrete estiver presente), responde `202`:

- com lembrete valido, resolve o staff direto de `staff_login_hints` (sem
  telefone digitado) e atualiza `last_used_at`; lembrete invalido ou expirado
  e ignorado e a UI volta a pedir o telefone;
- com telefone: normaliza e calcula `phone_hash` com `identity_hash_secret`
  (mesmo HMAC de `verified_identities`, verificado em `app/web_auth/service.py`)
  e procura `staff_members` com `status = 'active'`;
- **anti-enumeracao**: telefone fora da tabela recebe o mesmo `202` com
  `challenge_id` sintetico (UUID aleatorio, nao persistido; o confirm dele cai
  no mesmo `400` de desafio desconhecido/expirado). A resposta nunca revela
  quem e staff. A negativa e logada internamente com hash truncado;
- **a resposta nao varia com a entrega**: diferente do fluxo de cliente, o
  start staff devolve `202` mesmo se o envio WhatsApp falhar — um `503` aqui
  denunciaria quem e staff, ja que o desafio sintetico nunca toca a entrega.
  Falha de envio vira log interno (`support_console_auth_delivery_failed`) e o
  operador simplesmente pede outro codigo. O canal lateral de timing residual
  (envio real demora mais que o sintetico) fica registrado como risco aceito;
- staff valido: cria desafio OTP com as protecoes existentes (expiracao,
  tentativas, cooldown de reenvio, rate limit por IP e por telefone) e envia
  pelo adapter de entrega ja usado no OTP de cliente;
- multiplas sessoes por operador sao permitidas (desktop + notebook);
- limpeza oportunista: apaga `staff_sessions` expiradas neste momento.

`POST /web/support/auth/confirm` — body `{ "challenge_id", "code" }`:

- consome o desafio (comparacao por digest, tentativas decrementadas);
- exige que o `phone_hash` do desafio exista em `staff_members` ativo no
  momento do confirm (um desafio iniciado pelo fluxo de cliente para um
  telefone staff continua sendo prova de posse do mesmo numero; a checagem
  contra a tabela e o que autoriza);
- gera token `secrets.token_urlsafe(32)`, grava `staff_sessions` com o HMAC
  do token (`expires_at` = proxima 4h no fuso do time) e emite os cookies:

```text
Set-Cookie: sfa_staff_session=<token>; HttpOnly; Secure; SameSite=Lax;
            Path=/web/support; Max-Age=<segundos ate as 4h>
Set-Cookie: sfa_staff_hint=<token2>; HttpOnly; Secure; SameSite=Lax;
            Path=/web/support/auth; Max-Age=<SUPPORT_STAFF_HINT_TTL_DAYS>
```

- `Path=/web/support` faz o browser nem enviar o cookie para o resto do site
  (o lembrete e ainda mais restrito: so viaja para `/web/support/auth`);
- o servidor e a fonte de verdade da expiracao; o `Max-Age` so acompanha;
- resposta: `{ "display_name": "Renan", "expires_at": "..." }`;
- codigo invalido/expirado: `400 invalid_or_expired_code` (mesmo contrato do
  web_auth), inclusive para o challenge sintetico da anti-enumeracao.

`GET /web/support/auth/session` — `{ "authenticated": true, "display_name",
"expires_at" }` ou, sem sessao valida, `401` com corpo
`{ "authenticated": false, "hint": { "display_name": "Renan" } | null }` — e o
que permite a tela de login mostrar o botao de 1 clique. E o guard de rota da
UI.

`POST /web/support/auth/logout` — apaga a linha da sessao e expira o cookie de
sessao. Com `{ "forget_device": true }`, remove tambem o lembrete ("esquecer
este dispositivo"); sem isso, o lembrete sobrevive ao logout.

### Dependencia de rota (`require_staff_session`)

Toda rota `/web/support/*` (exceto `auth/*`) usa a dependencia que:

1. le o cookie, calcula o HMAC e busca `staff_sessions` com
   `expires_at > now()` **join** `staff_members.status = 'active'`
   (desativar um staff derruba as sessoes vivas dele no ato);
2. devolve `StaffPrincipal(staff_id, display_name)` para handlers e auditoria;
3. falha com `401` e detail generico (sem eco de identificadores).

Escritas (Fase B) exigem adicionalmente o cabecalho
`X-Requested-With: XMLHttpRequest` (mitigacao CSRF alem do `SameSite=Lax`).

### UX da tela de login (contrato com o frontend)

- campo de codigo unico com 6 celulas: aceita colar e envia sozinho no sexto
  digito;
- reenviar codigo com countdown visivel (o cooldown ja existe no servico);
- "entrar com outro numero" (dispositivo compartilhado) e "esquecer este
  dispositivo" (remove o lembrete) sempre disponiveis;
- ritual diario alvo: ~10 segundos — 1 clique, ler o codigo, 6 teclas.

### Gestao de staff (sem restart, sem env var)

`scripts/manage_staff.py` (usa `DATABASE_URL` + `IDENTITY_HASH_SECRET` do
ambiente, nunca imprime telefone completo):

```bash
python scripts/manage_staff.py add "+5511999999999" --name "Renan"
python scripts/manage_staff.py disable "+5511999999999"
python scripts/manage_staff.py list   # display_name, last4, status
```

Adicionar/remover operador e um comando; nada de editar env nem reiniciar
servico na VPS.

### Resiliencia e rotacao

- **Break-glass**: se a entrega de OTP cair (Hermes/Meta indisponivel), o
  time nao fica cego — `GET /support` com `X-API-Key` continua funcionando
  servidor-servidor.
- **Rotacao de `identity_hash_secret`** invalida os `phone_hash` de
  `staff_members` (e de `verified_identities`, como hoje). Procedimento: rodar
  `manage_staff.py add` novamente para cada operador apos a rotacao. Registrado
  aqui para nao virar surpresa silenciosa.

### Evolucoes futuras (fora do escopo das Fases A-C)

- **Aprovar respondendo no WhatsApp** (zero digitacao no desktop): exige
  interceptar mensagens inbound do fluxo do bot para rotear ao auth, mais
  number-matching na tela contra aprovacao distraida. Acoplamento
  transporte-auth a avaliar antes de existir.
- **Passkeys/WebAuthn** (Windows Hello) apos o primeiro OTP: eliminaria o
  WhatsApp do login recorrente, ao custo de biblioteca e tabela de
  credenciais novas.

## Configuracao Nova

Tudo escuro por padrao, no padrao `enable_support_inbox`:

```text
ENABLE_SUPPORT_CONSOLE=false          # liga /web/support/* (fachada + auth)
SUPPORT_CONSOLE_TIMEZONE=America/Sao_Paulo  # corte da sessao e das metricas
SUPPORT_STAFF_SESSION_EXPIRY_HOUR=4   # sessao morre na proxima 4h local
SUPPORT_STAFF_HINT_TTL_DAYS=90        # lembrete de dispositivo (1 clique)
SUPPORT_SLA_MINUTES_URGENT=60
SUPPORT_SLA_MINUTES_HIGH=120
SUPPORT_SLA_MINUTES_NORMAL=480
SUPPORT_SLA_MINUTES_LOW=1440
SUPPORT_CONSOLE_ACTIVE_CASES_CAP=500  # teto do conjunto ativo em memoria

# Rate limits proprios da fachada (separados do chat publico):
SUPPORT_OTP_START_PER_PHONE_PER_HOUR=5
SUPPORT_OTP_START_PER_IP_PER_HOUR=20
SUPPORT_CONSOLE_READS_PER_SESSION_PER_MINUTE=120
```

Flag desligada -> `404` em toda a superficie (mesmo comportamento do inbox).

## Semaforo, Ordenacao E Relogio Unico

Decisao revisada: **o SQL so filtra e limita; todo o calculo acontece em
Python, num unico codigo**. A fila operacional e pequena por natureza (casos
nao-fechados), entao ordenar em memoria e mais simples e elimina a classe de
bugs de "duas fontes de verdade" (SQL vs Python) e "dois relogios" (banco vs
aplicacao).

### Busca do conjunto ativo

```sql
SELECT sc.id, ..., now() AS db_now       -- relogio do banco na mesma query
FROM support_cases sc JOIN domains d ON d.id = sc.domain_id
WHERE sc.status NOT IN ('closed', 'cancelled')
  AND (%s::text IS NULL OR d.name = %s)
ORDER BY sc.opened_at ASC
LIMIT %s                                  -- SUPPORT_CONSOLE_ACTIVE_CASES_CAP
```

- usa o indice existente `idx_support_cases_domain_status_opened`;
- `db_now` alimenta todo o calculo de SLA — como `opened_at` vem do mesmo
  relogio, nao existe drift;
- se o cap for atingido, a resposta traz `truncated: true` e um warning e
  logado. Valvula de escape documentada: se o backlog ativo um dia passar de
  ~1000 casos, persistir `deadline_at` como coluna indexada e voltar a
  ordenacao para o SQL. Ate la, e otimizacao prematura.

### `compute_sla` (funcao pura, `app/support/sla.py`)

```text
compute_sla(priority, opened_at, status, db_now, settings,
            waiting_seconds=0) ->        # waiting_seconds: Fase B
  deadline_at     # opened_at + SLA(priority) + waiting_seconds
  elapsed_ratio   # tempo ativo consumido / SLA(priority)
  color           # green < 0.6 <= yellow <= 1.0 < red
  paused          # waiting_customer | pending_consent
  explanation     # "urgente, aberto ha 6h12, prazo estourado ha 4h12"
```

- **Fase A**: caso pausado nunca fica vermelho e a UI exibe chip neutro
  "aguardando cliente"; o ratio exibido e o total (aproximacao declarada).
- **Fase B**: `waiting_seconds` vem dos eventos (soma dos intervalos entre
  `wait_customer` e `resume`), e o relogio pausa de verdade.
- Textos de `explanation` sao staff-facing em pt-BR correto (ortografia plena,
  como as mensagens de cliente).

### Ordenacao "attention" e filtro por cor (em Python)

```text
chave = (estourado_e_nao_pausado DESC, peso_prioridade DESC, opened_at ASC)
peso: urgent=4, high=3, normal=2, low=1
```

- deterministico: mesma entrada, mesma fila;
- filtro `color` e aplicado sobre o conjunto ja calculado — trivial e sempre
  consistente com a cor exibida;
- paginacao (`limit`/`offset`) aplicada apos ordenar/filtrar em Python;
- historico (fechados/cancelados) nao passa por SLA: paginacao SQL normal por
  `opened_at DESC`.

## Contratos Da Fachada

### `GET /web/support/cases` (Fase A)

Query: `view` (`active` padrao | `history`), `status`, `domain`, `color`,
`sort` (`attention` padrao | `opened_at`), `assignee` (`me`, Fase B),
`limit`, `offset`. `pending_consent` so aparece com filtro explicito
(comportamento herdado do repositorio). Banco indisponivel ->
`503 support_inbox_storage_unavailable`, mesmo contrato do inbox interno.

Resposta = resumo atual do inbox + blocos novos:

```json
{
  "sla": {
    "deadline_at": "2026-07-02T18:00:00Z",
    "elapsed_ratio": 1.7,
    "color": "red",
    "paused": false,
    "explanation": "urgente, aberto há 6h12, prazo estourado há 4h12"
  },
  "assignee": { "display_name": "Renan" },
  "truncated": false
}
```

(`assignee` null ate a Fase B.)

### `GET /web/support/cases/{case_id}` (Fase A)

Igual ao `SupportCaseDetailResponse` interno (transcript sanitizado,
referencias, confianca, contato autorizado via consent gate) + blocos `sla` e
`assignee` + historico de eventos (Fase B).

### `POST /web/support/cases/{case_id}/transition` (Fase B)

```json
{ "action": "claim" | "release" | "wait_customer" | "resume" | "close" | "cancel",
  "note": "opcional, curto, sanitizado" }
```

Matriz de transicoes (tudo fora disso -> `409 invalid_transition` com o status
atual no detail):

```text
open              -> claim         -> in_progress   (seta assignee; exige caso sem dono)
in_progress       -> release       -> open          (limpa assignee; devolve a fila)
in_progress       -> wait_customer -> waiting_customer
waiting_customer  -> resume        -> in_progress
in_progress       -> close         -> closed        (closed_at = now())
open|in_progress  -> cancel        -> cancelled     (closed_at = now())
```

Concorrencia por compare-and-swap (padrao do consent gate), ex. claim:

```sql
UPDATE support_cases
SET status = 'in_progress', assignee_staff_id = %s, updated_at = now()
WHERE id = %s AND status = 'open' AND assignee_staff_id IS NULL
```

`rowcount = 0` -> nada foi escrito; a transacao le o status/dono atual e
responde `409` com esse estado (evento so e inserido quando o UPDATE vence).
Dois operadores clicando juntos: exatamente um vence, o outro ve quem assumiu.
Evento auditavel inserido **na mesma transacao** do UPDATE — commit e rollback
sempre em conjunto.

Decisao v1: `claim` exige caso sem dono; as demais acoes qualquer staff ativo
pode executar (time pequeno, tudo auditado). Restricao por dono fica para
quando houver papeis.

### Migration 015 (Fase B)

```sql
ALTER TABLE support_cases
  ADD COLUMN assignee_staff_id UUID REFERENCES staff_members(id);
CREATE INDEX idx_support_cases_assignee ON support_cases (assignee_staff_id)
  WHERE assignee_staff_id IS NOT NULL;

CREATE TABLE support_case_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id UUID NOT NULL REFERENCES support_cases(id),
  actor_staff_id UUID NOT NULL REFERENCES staff_members(id),
  action TEXT NOT NULL,                -- claim/release/wait_customer/...
  from_status TEXT NOT NULL,
  to_status TEXT NOT NULL,
  note_sanitized TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_support_case_events_case
  ON support_case_events (case_id, created_at);
```

`assigned_team` (coluna de equipe da 009) fica intocada; dono individual vive
em `assignee_staff_id`, historico em `support_case_events`.

### `GET /web/support/metrics` (Fase C)

Query: `window` (`14d` | `30d`), `domain` opcional. Resposta:

```json
{
  "backlog": { "by_color": {"green": 3, "yellow": 2, "red": 1, "paused": 2},
               "by_status": {"open": 4, "in_progress": 2},
               "truncated": false },
  "throughput": [ {"day": "2026-07-01", "opened": 5, "closed": 3} ],
  "escalation_reasons": [ {"reason_code": "low_confidence", "count": 12} ],
  "feedback": { "helpful": 34, "not_helpful": 6, "helpful_rate": 0.85,
                "unknown_domain_count": 3, "sample_note": "amostra pequena" },
  "response_times": { "median_seconds_to_first_action": null,
                      "median_seconds_to_close": null }
}
```

Fontes (verificadas no schema):

- **backlog**: mesmo caminho Python da fila (`compute_sla` sobre o conjunto
  ativo) — uma fonte de verdade so;
- **throughput**: `opened_at` / `closed_at` agrupados por dia na janela
  (`closed_at` garantido pela constraint da 009 em fechados/cancelados);
  cortes diarios no fuso `SUPPORT_CONSOLE_TIMEZONE` (default
  `America/Sao_Paulo`) — dia cortado em UTC deslocaria o fim da tarde do
  time para o dia seguinte;
- **escalation_reasons**: `jsonb_array_elements_text(reason_codes)` na janela;
- **feedback**: join direto `feedback.chat_audit_id -> chat_audits.domain_id`
  (migration 004; `idx_feedback_created` cobre a janela). Feedback `orphan`
  (sem `chat_audit_id`) entra em `unknown_domain_count`, nunca some;
- **response_times**: null ate a Fase B; depois, medianas via
  `support_case_events` (criacao -> primeira acao) e `closed_at - opened_at`.

`helpful_rate` sempre acompanhado do volume absoluto.

## Frontend (repo ask-host-genius)

Fora deste repo; este plano fixa contrato e regras:

- rota interna `/team`, guardada por `GET /web/support/auth/session`;
- telas Fase A: login OTP (telefone + codigo), fila (semaforo, explicacao,
  filtros, dono), detalhe (transcript, referencias, contato autorizado);
- telas Fase B: botoes de transicao com confirmacao; filtro "meus casos";
- tela Fase C: painel com as quatro visoes + medianas quando existirem;
- chamadas same-origin para `/web/support/*`; o proxy Nginx ja roteia `/web/*`
  para o backend (ver
  [chat-ordens-frontend-proxy.md](../runbooks/chat-ordens-frontend-proxy.md));
- semaforo, prazo, ordenacao, explicacao e permissao vem prontos do backend; a
  UI nao recalcula regra de negocio;
- nenhum segredo, nenhum `X-API-Key`, nenhum telefone bruto no cliente.

## Observabilidade

Eventos `log_event` (sem PII; hashes truncados; nunca telefone, transcript,
nota de operador ou token):

- `support_console_auth_started` (staff_match boolean, hash truncado)
- `support_console_auth_confirmed` (staff_id)
- `support_console_auth_denied` (motivo generico)
- `support_console_listed` (view, filtros presentes, contagem, sort, truncated)
- `support_console_case_viewed` (case_id, status, turn_count)
- `support_console_transition` (case_id, action, from/to, actor_staff_id)
- `support_console_metrics_viewed` (window, domain presente)

## Seguranca (consolidado do hardening)

- Fachada dark por padrao; `404` com flag desligada, inclusive auth.
- Cookie staff proprio, `HttpOnly` + `Secure` + `SameSite=Lax` +
  `Path=/web/support`; token 256-bit aleatorio, armazenado como HMAC.
- Sessao expira na proxima 4h da manha (fuso do time), sem renovacao;
  desativar staff derruba sessoes vivas e lembretes (join com
  `status = 'active'` em cada request).
- Lembrete de dispositivo nao autentica: sozinho, apenas dispara OTP para o
  WhatsApp do proprio operador. Nasce somente apos login bem-sucedido
  (anti-enumeracao preservada) e morre com "esquecer este dispositivo" ou
  com o staff desativado.
- Anti-enumeracao no start; protecoes de brute-force do OTP herdadas
  (expiracao, tentativas, cooldown, rate limit por IP e por telefone).
- CSRF nas escritas: `SameSite=Lax` + cabecalho `X-Requested-With`.
- Rate limit proprio da fachada, separado do chat publico.
- Transcript e contato chegam sanitizados/consentidos do pipeline; o console
  nao re-processa nem enriquece PII.
- `403`/`401` com detail generico, sem eco de identificadores.

## Prontidao, Migrations E Rollout

- **Readiness**: `ENABLE_SUPPORT_CONSOLE=true` exige persistencia PostgreSQL
  ativa (tabelas staff) e entrega de OTP configurada. Combinacao invalida
  aparece no readiness como alerta, no mesmo padrao Auth + historico +
  handoff ja usado pela frente de identidade.
- **Schema contract**: tabelas, indexes e constraints das migrations 014 e
  015 entram em `app/db/schema_contract.py` (`REQUIRED_*`), para a guarda de
  schema cobrir o console como cobre o resto do banco.
- **Migrations aditivas**: 014 cria tabelas novas; 015 adiciona coluna
  nullable e tabela nova — sem rewrite de tabela, sem downtime esperado.
- **Rollout da Fase A** (staging antes de prod):
  1. aplicar a migration 014 pelo fluxo padrao de deploy;
  2. cadastrar operadores com `scripts/manage_staff.py add`;
  3. ligar `ENABLE_SUPPORT_CONSOLE` no staging;
  4. smoke pela API: login OTP real, fila com semaforo, detalhe de caso,
     logout, telefone nao-staff negado — registrar o roteiro em runbook novo
     `runbooks/support-console-smoke.md` (a criar na entrega da Fase A);
  5. deploy da tela `/team` no `ask-host-genius` (Juliano) e repetir o smoke
     pela UI;
  6. promover a prod com os mesmos passos.
- `docs/documentation-status.md` e atualizado quando a Fase A entregar
  contrato HTTP e migration (regra do git-flow).

## Fases E Arquivos Provaveis

### Fase A - auth staff + fila com semaforo (leitura)

- `migrations/014_support_console_staff.sql` (staff_members, staff_sessions)
- `app/support/sla.py` (novo: `compute_sla`, ordenacao, filtro por cor)
- `app/support/staff_auth.py` (novo: servico OTP staff + sessoes)
- `app/api/routes/web_support.py` + `app/api/schemas/web_support.py` (novos)
- `app/support/repository.py` (conjunto ativo com `db_now` + cap; historico)
- `app/core/config.py` (flags e SLAs) · `app/main.py` (router condicional)
- `app/db/schema_contract.py` (objetos da 014) · readiness em `app/health/`
  (alerta para combinacao invalida de flags)
- `scripts/manage_staff.py` (novo)
- `tests/test_support_staff_auth.py`, `tests/test_support_sla.py`,
  `tests/test_web_support_console.py`
- `docs/architecture/integration-contracts.md` (contrato da fachada)

### Fase B - escrita auditada + dono na fila

- `migrations/015_support_case_events.sql` (eventos + `assignee_staff_id`)
- `app/db/schema_contract.py` (objetos da 015)
- `app/support/transitions.py` (novo) + extensao do repositorio
- pausa real do relogio em `compute_sla` (via `waiting_seconds` dos eventos)
- filtro `assignee=me` na fila; `assignee` no contrato
- `tests/test_support_transitions.py` (+ integracao postgres opt-in)

### Fase C - metricas

- `app/support/metrics.py` (novo, consultas agregadas)
- endpoint `/web/support/metrics` + schema
- `tests/test_support_metrics.py`

## Validacao

Por fase:

```bash
python -m pytest
python -m compileall app tests scripts
```

- **Fase A**:
  - auth: flag off -> 404; telefone nao-staff -> 202 identico + confirm falha;
    fluxo staff completo com entrega fake; expiracao na proxima 4h com
    relogio e fuso injetados; staff desativado com sessao viva -> 401 no
    request seguinte; logout;
  - lembrete: 1 clique dispara OTP sem telefone; lembrete roubado nao
    autentica nem lista casos; logout preserva o lembrete e
    `forget_device: true` remove; staff desativado invalida o lembrete;
  - `compute_sla`: limiares de cor, pausado nunca vermelho, explicacao;
  - fila: ordenacao attention deterministica, filtro por cor, paginacao em
    Python, cap com `truncated`;
  - privacidade: caplog sem telefone/PII/token; contrato das respostas;
  - readiness acusa flag ligada sem persistencia/entrega configuradas;
  - start staff com entrega quebrada continua respondendo `202`.
- **Fase B**: matriz completa de transicoes validas/invalidas; concorrencia
  (dois claims -> um vence, outro 409); evento na mesma transacao (rollback
  conjunto); constraint `closed_at`; integracao postgres opt-in.
- **Fase C**: agregacoes contra fixtures deterministicas, incluindo feedback
  orphan no bucket `unknown_domain`; janela e filtro de dominio.
- Sempre: `tests/test_docs_links.py`.

Nao requer eval de dominio: o console nao toca prompt, retrieval nem decisao
de handoff — apenas le e transiciona casos ja criados.

## Riscos Tecnicos

- **Entrega de OTP indisponivel bloqueia login staff**: mitigado pelo
  break-glass (`GET /support` com `X-API-Key`) e pelas sessoes de 24h ja
  emitidas continuarem validas.
- **Rotacao de `identity_hash_secret` invalida hashes staff**: procedimento de
  recadastro via `manage_staff.py` documentado acima.
- **Cap do conjunto ativo atingido**: resposta marca `truncated` e loga
  warning; valvula de escape (coluna `deadline_at` indexada) documentada.
- **Drift entre repos (contrato da fachada vs UI)**: contrato entra em
  `integration-contracts.md` antes da tela; mudancas passam por la primeiro.
- **Desafio OTP compartilhado entre fluxo cliente e staff**: mitigado — o
  confirm staff so autoriza se o `phone_hash` do desafio estiver em
  `staff_members` ativo; posse do numero continua sendo o fator.
- **Canal lateral de timing no start staff**: o envio real demora mais que o
  desafio sintetico. Aceito como residual — o rate limit por IP/telefone
  limita a sondagem; se um dia incomodar, mover o envio para depois da
  resposta.
- **Cortes diarios das metricas e da sessao**: dependem do fuso configurado;
  testes fixam `SUPPORT_CONSOLE_TIMEZONE` e injetam o relogio para nao
  flutuar com o ambiente.

## Dependencias E Sequencia

1. Fase A depende so da migration 014 (persistencia: Renan) e da entrega de
   OTP ja viva em producao.
2. Fase B depende da migration 015 (persistencia: Renan).
3. Fase C depende da Fase A; medianas de tempo dependem da B.
4. Deploy do frontend `/team` na VPS: Juliano (mesmo fluxo do
   `deploy_ask_host_genius`).
