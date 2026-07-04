# Plano Tecnico - Status De Atendimento Para O Cliente (Web Chat)

Status: proposto em 2026-07-03. Nenhuma fase iniciada. Plano de produto:
[web-chat-customer-ticket-status-plan.md](web-chat-customer-ticket-status-plan.md).
E a metade cliente da visao V3 do
[web-chat-evolution-plan.md](web-chat-evolution-plan.md); o console do time
([support-team-console-tech-plan.md](support-team-console-tech-plan.md)) e a
metade interna, sobre os mesmos dados.

> **Decisao (2026-07-04) — rebaixado (opcao C):** o painel `/web/tickets`
> separado (pull) **nao sera construido como estava**; o status vira um bloco no
> widget web existente + CTA "continuar no WhatsApp". O "fechar o ciclo" passou
> para a frente de WhatsApp
> ([whatsapp-support-bridge-tech-plan.md](whatsapp-support-bridge-tech-plan.md)).
> As secoes abaixo (projecao cliente-safe, autorizacao) seguem validas como
> referencia e para o bloco no widget.

## Decisao Arquitetural

Uma **fachada web de cliente** read-only sobre `support_cases`, autenticada pela
mesma sessao verificada por OTP que o web chat ja usa. Nada de canal paralelo de
dados, nada de segredo no browser, e — critico — **nenhuma reutilizacao da
projecao do time**:

```text
Browser (ask-host-genius, web chat publico)
  -> /web/auth/whatsapp/*   (OTP -> verified_identity -> customer_id) [ja existe]
  -> /web/tickets/*         (exige customer_id resolvido da sessao)
  -> CustomerTicketRepository (leitura escopada por customer_id)
  -> project_customer_ticket() (projecao ESTREITA, modulo proprio)
  -> support_cases + messages (leitura)

Time (staff)  -> /web/support/*  (sessao staff, OTP dedicado)   [intocado]
Integracoes   -> GET /support, /internal/support-cases (X-API-Key) [intocado]
```

Reusos deliberados:

- **Auth de cliente**: o cookie de sessao web publica (`web:<uuid>`,
  `app/core/web_session.py`) e o `CurrentIdentityResolver`
  (`app/identity/current.py`) ja resolvem `customer_id` a partir da sessao
  verificada — exatamente como `POST /web/chat` faz hoje
  ([web_chat.py](../../app/api/routes/web_chat.py) `_resolve_identity_context`).
  Zero auth nova.
- **Indice ja existe**: `idx_support_cases_customer ON support_cases
  (customer_id, opened_at DESC) WHERE customer_id IS NOT NULL` (migration 009)
  cobre exatamente a query `WHERE customer_id = ? ORDER BY opened_at DESC`.
- **Transcript ja sanitizado**: `messages` guarda o conteudo ja sanitizado na
  escrita; a primeira mensagem `role='user'` e a pergunta de abertura do
  proprio cliente.

**Separacao fisica da projecao (a decisao de seguranca central):** o
`build_case_context`/`SupportCaseContext` (`app/support/context.py`) e a
projecao do **time** — expoe `customer.email`, `reason_codes`, `references` e
`confidence` por turno. O cliente **nunca** toca nisso. A projecao dele vive num
modulo proprio (`app/support/customer_tickets.py`), com dataclass propria e
whitelist explicita de campos. A fronteira "sanitizado pro time != seguro pro
cliente" e garantida por **separacao de modulo**, nao por vigilancia no code
review.

## Autenticacao Do Cliente

- A sessao verificada e a mesma da V0/V1: cookie `web:<uuid>` +
  `verified_identities` via `WebWhatsAppAuthService.get_session_identity`.
- `GET /web/tickets` resolve `customer_id` no backend via
  `CurrentIdentityResolver.resolve(session_id)`. `customer_id is None`
  (anonimo ou sessao nao verificada) -> resposta anonima, lista vazia.
- Sessao efemera: se o cliente troca de aparelho/limpa cookie, a sessao nao
  esta mais vinculada e `customer_id` volta `None`. Para ver os tickets ele
  **re-autentica por OTP** (mesmo fluxo `/web/auth/whatsapp/*`). A UI mostra o
  convite a confirmar o WhatsApp, nunca uma lista vazia crua.
- Depende de `enable_web_whatsapp_auth=true`: com a flag off, o
  `web_auth_service` e `None`, a sessao nunca autentica e a feature nao tem como
  resolver cliente. Isso vira alerta de readiness (ver Prontidao).

Contraste com o staff: o console usa cookie proprio `Path=/web/support` e tabela
`staff_sessions`. O cliente **nao** usa nada disso — reaproveita a sessao publica
existente. Sem colisao de rota (`/web/tickets` != `/web/support`) e sem colisao
de cookie (o cookie publico ja viaja para `/web/*`).

## Modelo De Dados

### Fase A - zero migration

Leitura pura sobre `support_cases` (migration 009 + 013 + 015) pelo indice de
cliente que ja existe. **Nenhuma tabela nova, nenhuma coluna nova, nenhuma
mudanca no `schema_contract.py`.** Este e o corte mais barato e seguro.

Colunas lidas: `id`, `domain_id`->`domains.name`, `status`, `channel`,
`request_id`, `opened_at`, `updated_at`, `closed_at`, `conversation_id`,
`customer_id`. **Nao** lidas para o cliente: `priority`, `reason_codes`,
`context_snapshot_sanitized`, `assignee_staff_id`, `assigned_team`.

Status permitidos (constraint `support_cases_status_check`, migration 013):
`pending_consent`, `open`, `in_progress`, `waiting_customer`, `closed`,
`cancelled`. `pending_consent` **nunca** e retornado ao cliente.

### Fase B - resposta do cliente (precisa de migration 016)

`support_case_events` hoje e **staff-only**: `actor_staff_id UUID NOT NULL
REFERENCES staff_members(id)` (migration 015). Uma resposta do cliente nao cabe
ali. Duas opcoes:

- **Opcao 1 (recomendada): generalizar o ator do evento.** Migration 016:
  `actor_staff_id` vira nullable, adiciona `actor_kind TEXT NOT NULL DEFAULT
  'staff' CHECK (actor_kind IN ('staff','customer'))` e
  `actor_customer_id UUID NULL REFERENCES customers(id)`, com CHECK de que
  exatamente um ator esta preenchido conforme `actor_kind`. O historico passa a
  descrever tanto acao de operador quanto resposta de cliente numa trilha so.
- **Opcao 2: nao usar eventos para a resposta do cliente.** A resposta vira so
  uma `messages` nova + a transicao de status; o "quem respondeu" fica implicito
  pelo `role='user'` da mensagem. Mais simples, mas quebra a trilha unica de
  auditoria por caso.

Recomendacao: Opcao 1 — mantem uma trilha de auditoria por caso e o console do
time passa a mostrar "cliente respondeu" no mesmo historico. Detalhar na entrega
da Fase B.

### Fase C - notificacao ao cliente (sem tabela nova)

Reusa `operational_outbox` + `customers.email` + `customer_preferences` (todos
ja existentes). Ver a secao propria abaixo — tem uma pegadinha de privacidade.

## Projecao Cliente-Safe

Modulo novo `app/support/customer_tickets.py`. Dataclass e mapper puros:

```text
CustomerTicketSummary:
  ticket_code      # = request_id (o codigo de suporte que o cliente ja tem)
  status           # interno, para logica de UI
  status_label     # traduzido (mapa abaixo)
  domain_label     # rotulo amigavel do dominio
  opened_at
  last_update_at   # = updated_at

CustomerTicketDetail(CustomerTicketSummary):
  subject          # primeira mensagem role='user' do transcript (texto do proprio cliente)
  closed_at        # quando aplicavel
  timeline         # opcional (Fase A+/B): eventos projetados sem identidade de operador
```

Mapa de status (calibravel na copy, pt-BR pleno):

| status interno | status_label |
| --- | --- |
| `open` | "Recebido, na fila" |
| `in_progress` | "Em analise por um atendente" |
| `waiting_customer` | "Aguardando sua resposta" |
| `closed` | "Resolvido" |
| `cancelled` | "Encerrado" |
| `pending_consent` | filtrado antes da projecao — nunca chega aqui |

Campos que a projecao **jamais** copia: `priority`, `reason_codes`,
`confidence`, `references`/nomes de KB, `assignee_*`/nome de operador,
`context_snapshot_sanitized`, e-mail/telefone. Teste dedicado assevera que o
payload serializado nao contem nenhuma dessas chaves.

**Subject sem N+1**: a lista **nao** carrega transcript (so o scan indexado de
`support_cases`); o subject aparece so no detalhe, que ja segue
`conversation_id` para o transcript. Se o produto quiser a pergunta na lista,
otimizacao futura: `DISTINCT ON (conversation_id)` da primeira mensagem `user`,
ou uma coluna `subject` desnormalizada — nao no MVP.

## Repositorio

Modulo novo `app/support/customer_tickets.py` (nao estender
`SupportCaseRepository`, que e staff/inbox-oriented). `customer_id` e **sempre**
parametro obrigatorio da query — nunca opcional, nunca vindo do browser:

```python
class CustomerTicketRepository:
    def list_for_customer(self, *, customer_id: str, limit, offset)
        -> list[CustomerTicketSummary]: ...
    def get_for_customer(self, *, customer_id: str, ticket_code: str)
        -> CustomerTicketDetail | None: ...
```

`list_for_customer`:

```sql
SELECT sc.request_id, d.name, sc.status, sc.opened_at, sc.updated_at
FROM support_cases sc
JOIN domains d ON d.id = sc.domain_id
WHERE sc.customer_id = %s          -- bound, obrigatorio
  AND sc.status != 'pending_consent'
ORDER BY sc.opened_at DESC
LIMIT %s OFFSET %s
```

Usa `idx_support_cases_customer`. Defesa extra opcional: `AND sc.channel = 'web'`
— casos de WhatsApp nativo nao carregam o `customer_id` do web (canais
separados por design), entao o filtro por `customer_id` ja isola; o `channel`
e cinto-e-suspensorio.

`get_for_customer`:

```sql
SELECT ... FROM support_cases sc ...
WHERE sc.request_id = %s AND sc.customer_id = %s
  AND sc.status != 'pending_consent'
LIMIT 1
```

`request_id` casado com `customer_id` na mesma clausula — caso de outro cliente
(ou inexistente) retorna zero linhas -> `404`. Nunca `403` (nao confirmar
existencia). Segue `conversation_id` para pegar a primeira mensagem `user` como
`subject`.

## Contratos Da Fachada

### `GET /web/tickets` (Fase A)

- Auth: cookie de sessao web verificada. Anonima/nao verificada -> `200`
  `{ "status": "anonymous", "tickets": [] }`.
- `customer_id` resolvido no backend. Browser nunca envia `customer_id` nem
  telefone. Query: `limit`, `offset` (paginacao simples, limites do servidor).
- Banco indisponivel -> `503 ticket_storage_unavailable`.

```json
{
  "status": "verified",
  "tickets": [
    {
      "ticket_code": "…request_id…",
      "status_label": "Em analise por um atendente",
      "status": "in_progress",
      "domain_label": "Suporte VPS e WhatsApp",
      "opened_at": "2026-07-03T12:00:00Z",
      "last_update_at": "2026-07-03T13:10:00Z"
    }
  ]
}
```

### `GET /web/tickets/{ticket_code}` (Fase A)

- `ticket_code` = `request_id`. Resolve por `(request_id, customer_id)`. Nao
  pertence ao cliente -> `404`.

```json
{
  "ticket_code": "…",
  "status": "waiting_customer",
  "status_label": "Aguardando sua resposta",
  "subject": "Nao consigo acessar o painel apos a migracao",
  "domain_label": "Suporte VPS e WhatsApp",
  "opened_at": "…", "last_update_at": "…", "closed_at": null
}
```

### `POST /web/tickets/{ticket_code}/reply` (Fase B)

- Corpo `{ "message": "…" }`. Header `X-Requested-With: XMLHttpRequest` (CSRF,
  mesmo padrao das escritas do console).
- So o dono (`customer_id` da sessao) e so quando `status='waiting_customer'`.
- Compare-and-swap, padrao do consent gate/console:

```sql
UPDATE support_cases
SET status = 'in_progress', updated_at = now()
WHERE request_id = %s AND customer_id = %s AND status = 'waiting_customer'
```

  `rowcount = 0` -> `409 invalid_state` com o status atual. Quando vence: insere
  a `messages` (role='user', channel='web', sanitizada pelo mesmo caminho de
  escrita ja usado), grava o evento (`actor_kind='customer'`, ver migration 016)
  e enfileira notificacao ao time (`whatsapp.message.requested`, reuso do
  Sprint 5) — tudo **na mesma transacao**.
- Rate limit por sessao/caso; idempotencia por conteudo+turno.
- Fecha o loop hoje morto: em `waiting_customer` o time espera e o cliente nao
  tem canal de volta sem abrir chat novo.

## Notificacao De Status Ao Cliente (Fase C) - a pegadinha

> **Revisao (2026-07-04):** a conclusao "so e-mail" abaixo foi **superada** pela
> frente de ponte WhatsApp<->console
> ([whatsapp-support-bridge-tech-plan.md](whatsapp-support-bridge-tech-plan.md)):
> com `wa_id` cifrado e escopado ao caso aberto (purgado no fechamento), o
> WhatsApp volta a ser canal viavel para status/atendimento; o e-mail continua
> como canal paralelo. O texto abaixo permanece como o raciocinio original.

O reflexo natural seria "avisar o cliente no WhatsApp quando o status mudar",
reusando o `whatsapp.message.requested` do Sprint 5. **Nao da, pela propria
disciplina de privacidade do projeto:** o telefone bruto do cliente nunca e
persistido — so `phone_hash` + `phone_last4` (`verified_identities`,
`migrations/002_web_auth.sql`). E a mesma restricao que tornou o lembrete de
abandono de OTP impossivel por push (registrado no
[customer-identity-whatsapp-handoff-plan.md](customer-identity-whatsapp-handoff-plan.md),
Sprint 4b): nenhum job assincrono sabe para qual numero enviar.

Decisao decorrente:

- **Canal da notificacao ao cliente = e-mail, nao WhatsApp.** `customers.email`
  e guardado **legivel** de proposito (migration 013, coletado no consent gate,
  "a equipe usa para contato real") e ja e consentido. Um renderer
  `support_case + transicao -> email.message.requested` reusa o
  `operational_outbox` com um transporte de e-mail (novo do lado do dispatcher —
  frente do Juliano; o backend so enfileira o evento sanitizado).
- **Opt-out** por `customer_preferences` (tabela ja existe, migration 009): uma
  chave `notify_status_by_email`. Fallback: sem e-mail salvo -> so o modelo pull
  (Fase A) atende aquele cliente.
- **So transicoes que importam** ao cliente: `-> in_progress` ("um atendente
  assumiu"), `-> closed` ("resolvido"), `-> waiting_customer` ("precisamos de
  voce"). Nunca `pending_consent`, nunca churn interno.
- **Idempotencia**: `notify_customer:<case_id>:<to_status>`, um evento por
  transicao relevante.
- Dentro do escopo do consentimento LGPD ja dado ("contato direto da equipe"),
  com opt-out explicito.

Se o produto insistir em WhatsApp proativo ao cliente, isso exige **persistir o
telefone do cliente** (cru ou tokenizado reversivel) — decisao de privacidade
real, com o mesmo peso do gate LGPD, **fora** desta frente. Nao empurrar isso
para dentro da Fase C por conveniencia.

## Configuracao Nova

Escuro por padrao, no padrao das outras fachadas web:

```text
ENABLE_WEB_CUSTOMER_TICKETS=false     # liga /web/tickets/* (404 com flag off)
WEB_CUSTOMER_TICKETS_PER_SESSION_PER_MINUTE=60   # rate limit de leitura
WEB_CUSTOMER_TICKET_REPLY_PER_CASE_PER_HOUR=20   # Fase B
```

Flag off -> router nao montado (fora do OpenAPI, `404` em toda a superficie),
mesmo padrao do `ENABLE_SUPPORT_CONSOLE`.

## Prontidao, Migrations E Rollout

- **Readiness**: `ENABLE_WEB_CUSTOMER_TICKETS=true` exige
  `enable_web_whatsapp_auth=true` (sem auth, sem `customer_id`, feature inutil)
  e `PERSISTENCE_BACKEND=postgres` (sem casos, nada a mostrar). Combinacao
  invalida vira alerta, no mesmo padrao Auth + historico + handoff da frente de
  identidade.
- **Fase A: sem migration, sem schema_contract novo.** Rollout = ligar a flag no
  staging, smoke pela API (cliente verificado ve so os seus; anonimo lista
  vazia; caso alheio 404; `pending_consent` oculto), depois UI no
  `ask-host-genius` (Juliano), depois prod.
- **Fase B**: migration 016 (ator generico em `support_case_events`) +
  `schema_contract.py`; aditiva (coluna nullable + CHECK), sem rewrite.
- **Fase C**: sem tabela nova; depende de um transporte de e-mail no dispatcher
  (Juliano) e da chave de opt-out em `customer_preferences`.

## Frontend (repo ask-host-genius)

Fixa contrato e regras (implementacao fora deste repo):

- area do cliente **dentro do web chat publico** ja existente (nao e `/team`):
  um painel "Meus atendimentos" que aparece quando a sessao esta verificada;
- sessao nao verificada -> convite a confirmar WhatsApp (reusa o widget de OTP
  do consent gate), nunca lista vazia crua;
- chamadas same-origin para `/web/tickets/*`; o proxy Nginx ja roteia `/web/*`;
- status_label, subject e datas vem prontos do backend; a UI nao traduz status
  nem recalcula regra;
- nenhum segredo, nenhum `X-API-Key`, nenhum reason code, nome de operador,
  confianca ou referencia de KB no cliente.

## Observabilidade

`log_event` sem PII, hashes truncados, nunca telefone/e-mail/transcript/token:

- `customer_tickets_listed` (session_id_hash, count, authenticated)
- `customer_ticket_viewed` (ticket_code, status)
- `customer_ticket_view_denied` (motivo generico: anonimo | nao-dono)
- `customer_ticket_reply` (ticket_code, from/to status) — Fase B
- `customer_status_notify_enqueued` (case_id, to_status, channel='email') — Fase C

`customer_id` em log so como hash truncado; `ticket_code` (=request_id) ja e o
codigo publico de suporte, pode aparecer.

## Seguranca

- Fachada dark por padrao; `404` com flag off.
- **Autorizacao e o jogo todo**: `customer_id` sempre resolvido no backend e
  sempre clausula obrigatoria da query; `404` (nao `403`) em caso alheio;
  anonimo nunca enumera.
- Projecao em modulo proprio com whitelist; teste de campos proibidos no
  payload.
- Reuso da sessao publica existente (`HttpOnly`, `Secure` em prod,
  `SameSite=Lax`); sem cookie novo.
- CSRF nas escritas (Fase B): `SameSite=Lax` + `X-Requested-With`.
- Rate limit proprio, separado do chat publico e do console.
- Nada re-sanitizado aqui: o transcript/subject ja vem sanitizado da escrita.

## Fases E Arquivos Provaveis

### Fase A - leitura (sem migration)

- `app/support/customer_tickets.py` (novo: `CustomerTicketRepository` +
  `CustomerTicketSummary`/`Detail` + `project_customer_ticket`)
- `app/api/routes/web_tickets.py` + `app/api/schemas/web_tickets.py` (novos)
- `app/core/config.py` (flag + rate limits) · `app/main.py` (router condicional)
- readiness em `app/health/` (combinacao de flags)
- `tests/test_web_customer_tickets.py` (autorizacao A!=B, nao-enumeracao,
  `pending_consent` oculto, projecao sem campos proibidos, 404 alheio,
  status_label, 503 sem banco)
- `docs/architecture/integration-contracts.md` (contrato da fachada)
- `runbooks/web-customer-tickets-smoke.md` (a criar na entrega)

### Fase B - resposta em waiting_customer

- `migrations/016_case_event_actor.sql` (ator generico) + `schema_contract.py`
- extensao do repositorio (CAS + insert de `messages` + evento) e do contrato
- `tests/test_web_customer_tickets.py` (CAS, dono-only, estado invalido 409,
  integracao postgres opt-in)

### Fase C - notificacao por e-mail

- renderer `app/notifications/customer_status.py` (novo)
- chave de opt-out em `customer_preferences` + leitura no write path
- evento `email.message.requested` no outbox (transporte no dispatcher: Juliano)
- `tests/test_customer_status_notifications.py`

## Validacao

```bash
python -m pytest
python -m compileall app tests scripts
python -m pytest tests/test_docs_links.py
```

- **Fase A**: flag off -> 404; anonimo -> lista vazia sem enumerar; cliente
  verificado ve so os seus; caso de outro cliente -> 404; `pending_consent`
  nunca aparece; payload sem campo proibido (teste de whitelist); `503` sem
  banco; readiness acusa flag ligada sem auth/persistencia; caplog sem
  PII/telefone/e-mail/token.
- **Fase B**: matriz de estado (so `waiting_customer` aceita reply, resto 409);
  CAS concorrente (dois replies -> um vence); so o dono escreve; evento +
  mensagem na mesma transacao (rollback conjunto); integracao postgres opt-in.
- **Fase C**: renderer com opt-out respeitado; idempotencia por
  `case_id+to_status`; sem e-mail salvo -> nenhum evento; nunca notifica
  `pending_consent`.

Nao requer eval de dominio: nao toca prompt, retrieval nem decisao de handoff —
so le e transiciona casos ja criados (mesma justificativa do console).

## Riscos Tecnicos

- **Vazamento cross-customer** (o pior): mitigado por `customer_id` obrigatorio
  na query + `404` alheio + teste A!=B. Projecao em modulo separado impede
  vazar campo do time por descuido.
- **Reusar `build_case_context` (do time) no cliente**: proibido; mapper e
  dataclass proprios, teste de campos proibidos.
- **Sessao efemera confundir o cliente**: copy + re-OTP; limitacao documentada
  (identica a do consent gate).
- **Fase C sem telefone bruto**: resolvido indo por e-mail (consentido,
  legivel); WhatsApp proativo fica fora, exigiria decisao de PII propria.
- **`support_case_events` staff-only**: resolvido pela migration 016 (ator
  generico) antes da Fase B; nao forcar resposta de cliente na tabela atual.

## Dependencias E Sequencia

1. **Fase A** nao depende de nada novo (migration, secret, transporte): so
   codigo + a flag. E o menor passo entregavel — e o de maior valor imediato
   pro cliente.
2. **Fase B** depende da migration 016 (persistencia: Renan).
3. **Fase C** depende de um transporte de e-mail no dispatcher (Juliano) e da
   chave de opt-out.
4. UI no `ask-host-genius`: Renan (contrato) + deploy Juliano (mesmo fluxo do
   chat publico).
