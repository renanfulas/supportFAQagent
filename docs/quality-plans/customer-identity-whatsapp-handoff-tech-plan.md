# Plano técnico — gate de consentimento LGPD no handoff (Sprint 4b)

Plano de execução detalhado, em nível de arquivo/classe/endpoint/migration, para
implementar o Sprint 4b registrado em
[`customer-identity-whatsapp-handoff-plan.md`](./customer-identity-whatsapp-handoff-plan.md).
Este documento é o "como"; o outro é o "o quê / por quê". Revisão: 2026-07-01.

Princípios herdados do projeto (não negociar):
- Cada comportamento novo entra atrás de flag/estado explícito, com fallback seguro.
- **Nunca** persistir `session_id`/telefone cru; reusar `hash_session`, `sanitize_payload`.
- `support_case` nasce **na mesma transação** que reconhece a escalação — essa
  garantia de atomicidade (Sprint 4 original) **não pode ser quebrada** por este
  sprint. Ver "Decisão de arquitetura" abaixo — é o ajuste mais importante deste
  documento em relação à redação original do Sprint 4b.
- Migrations forward-only com ledger (`python -m scripts.migrate`). Última aplicada:
  `012_conversation_summaries.sql`. Próximas disponíveis: `013_`, `014_`.
- `python -m pytest` + `python -m compileall app tests scripts` em toda fatia.

---

## 1. Decisão de arquitetura (o ajuste que muda o plano original)

A redação original do Sprint 4b dizia "só após OTP confirmado: `support_case` é
criado". Ao mapear o código real (`app/db/operational.py::record_chat`), isso
quebraria uma garantia estrutural: hoje `_upsert_support_case` roda **dentro da
mesma transação** que persiste o turno escalado — é assim que o projeto garante
"nenhum turno reconhecido como escalação fica sem ticket". Adiar a criação do
`support_case` para uma request HTTP futura (depois do round-trip de OTP, que pode
levar minutos) quebra essa atomicidade e exige inventar um mecanismo novo de
correlação entre "aquele turno" e "este ticket que vai nascer depois".

**Desenho revisado:** o `support_case` continua nascendo **imediatamente**, na
mesma transação de hoje, sem mudar `_upsert_support_case`. O que muda é um novo
status intermediário, `pending_consent`, e o fato de que **a notificação ao time
(outbox + WhatsApp) só é enfileirada quando o consentimento é confirmado depois**,
não na criação do caso.

| | Hoje | Proposto |
| --- | --- | --- |
| `support_case` nasce | na transação do turno escalado | igual, sem mudança |
| Notificação ao time | enfileirada na mesma transação | **adiada** até consentimento |
| Correlação com o ticket depois | N/A | por `request_id` (já é coluna de `support_cases`, já está na resposta do widget) |
| Lembrete de 15 min | N/A | escaneia `support_cases`/`otp_challenges`, não precisa reconstruir nada |

Isso é estritamente melhor que a redação original: reaproveita 100% do código de
criação de ticket que já existe e já tem 31/31 testes de integração, e resolve o
problema de correlação de graça (o `request_id` já é uma coluna indexável em
`support_cases`, não precisa de tabela nova para isso).

---

## 2. Mapa de superfícies (todo arquivo/componente tocado)

| Camada | Arquivo/componente | Mudança |
| --- | --- | --- |
| Migration | `migrations/013_customer_contact_and_consent.sql` (novo) | `customers.email`; `support_cases_status_check` ganha `'pending_consent'`; `support_cases.consent_reminder_sent_at`; `otp_challenges.reminder_sent_at` |
| Config | `app/core/config.py` | novo `OTP_ABANDONMENT_REMINDER_MINUTES` (default 15), validação junto ao bloco `enable_web_whatsapp_auth` existente (config.py:299) |
| Backend — criação do caso | `app/db/operational.py::record_chat`/`_upsert_support_case` | passa `status='pending_consent'` quando o gate está ativo; **não** chama `_enqueue_support_team_notifications`/insere `handoff.requested` nesse caminho |
| Backend — novo endpoint | `app/api/routes/web_handoff.py` (novo) | `POST /web/handoff/consent` — recebe `request_id`+nome+e-mail, exige sessão já autenticada (`CurrentIdentityResolver`), promove o caso |
| Backend — schema/lógica de negócio | `app/support_cases/` (novo módulo, ou extensão de `app/db/operational.py`) | `promote_pending_case(...)`: valida ownership (o `customer_id` da sessão bate com o do caso), grava nome/e-mail em `customers`, muda status→`open`, enfileira outbox + notificação (reaproveita `_enqueue_support_team_notifications`) |
| Backend — leitura (inbox) | `app/support/repository.py::list_cases`, `app/api/routes/support.py` | **crítico**: sem filtro explícito de status, o inbox devolve tudo — precisa excluir `pending_consent` do resultado "sem filtro" por padrão (ver Risco #1) |
| Backend — schema contract | `app/db/schema_contract.py` | novo `email` em `customers`, novo status em `support_cases`, novas colunas de lembrete |
| Backend — job de lembrete | `scripts/remind_pending_otp.py` (novo, espelha `scripts/summarize_conversations.py`) | scan + reenvio de OTP via outbox (ver §6) |
| Backend — OTP (reaproveitado sem mudança) | `app/web_auth/service.py`, `app/web_auth/storage.py`, `app/api/routes/web_auth.py` | **nenhuma mudança de contrato** — `start`/`confirm`/`session` seguem iguais |
| Frontend | `app/static/chat/app.js`, `index.html`, `styles.css` | **maior superfície nova do sprint** — hoje o widget nunca chama `/web/auth/*`; precisa de UI para: confirmar intenção, capturar telefone, capturar código OTP, capturar nome/e-mail, exibir confirmação do ticket |
| Docs | `docs/architecture/integration-contracts.md` | novo contrato `POST /web/handoff/consent` |
| Docs | `docs/architecture/observability.md` | novos eventos de log (ver §7) |
| Testes | `tests/test_web_handoff.py` (novo), `tests/test_support_inbox.py` (estender), `tests/integration/test_phase0_postgres.py` (estender), `tests/test_web_auth.py` (sem mudança de contrato, só smoke) | ver §8 |
| Ops | novo systemd timer `supportfaq-consent-reminder.timer` (espelha `supportfaq-summarize.timer`) | roda a cada 5 min, escaneia janela de 15 min |

---

## 3. Modelo de dados — `migrations/013_customer_contact_and_consent.sql`

```sql
-- Contato explícito coletado no gate de consentimento (Sprint 4b).
ALTER TABLE customers ADD COLUMN email TEXT NULL;

-- Novo status intermediário: caso existe, mas o time ainda não pode contatar.
ALTER TABLE support_cases DROP CONSTRAINT support_cases_status_check;
ALTER TABLE support_cases ADD CONSTRAINT support_cases_status_check
  CHECK (status IN ('pending_consent', 'open', 'in_progress', 'waiting_customer', 'closed', 'cancelled'));

-- closed_at já tem CHECK amarrado a ('closed','cancelled'); pending_consent cai
-- naturalmente no ramo "NOT IN (closed, cancelled) => closed_at IS NULL", sem
-- precisar tocar essa constraint.

ALTER TABLE support_cases ADD COLUMN consent_reminder_sent_at TIMESTAMPTZ NULL;
ALTER TABLE otp_challenges ADD COLUMN reminder_sent_at TIMESTAMPTZ NULL;
```

Nota: `support_cases_closed_at_check` já cobre `pending_consent` sem alteração
(cai no ramo "não fechado" existente) — só a constraint de `status` precisa de
drop+recreate (Postgres não altera `CHECK` in-place).

---

## 4. Fluxo detalhado (endpoints exatos)

1. Cliente manda mensagem que o `handoff_service` já reconhece como escalação
   (`explicit_human_request` ou similar) — **sem mudança** no `ChatFlowService`.
   `POST /web/chat` responde com `escalated: true` (contrato inalterado).
2. **Widget** (novo, local, sem round-trip): ao ver `escalated: true`, renderiza
   um card "Antes de conectar você com um atendente, preciso confirmar seu
   WhatsApp. Qual seu número?" com um campo de telefone. Nenhuma chamada de
   backend ainda — decisão de UI pura.
3. Cliente informa o telefone → widget chama `POST /web/auth/whatsapp/start`
   (endpoint **existente**, sem mudança). Trata os erros já contratados (422
   telefone inválido, 429 rate limit/cooldown, 503 delivery indisponível).
4. Widget mostra campo de código → cliente digita → `POST
   /web/auth/whatsapp/confirm` (existente, sem mudança). Sessão fica autenticada
   (cookie já setado pelo fluxo atual).
5. Widget checa (via `GET /web/auth/session`, existente) ou via resposta do
   confirm se `customers.display_label`/`email` já existem para esse
   `customer_id` — **novo campo precisa ir na resposta do backend** (pequena
   mudança de contrato em `VerifiedSessionResponse`/`WhatsAppOtpConfirmRequest`,
   ver observação no schema abaixo). Se faltar, mostra campos de nome/e-mail.
6. Cliente envia nome/e-mail → widget chama **`POST /web/handoff/consent`**
   (novo endpoint), body `{request_id, name, email}`. `request_id` é o mesmo
   já devolvido pelo `/web/chat` no passo 1 (o widget já guarda isso hoje, para
   o "código de suporte").
7. Backend (`promote_pending_case`):
   - resolve identidade da sessão via `CurrentIdentityResolver` (rejeita com 401
     se não autenticado — **defesa contra pular o OTP chamando o endpoint
     direto**);
   - busca `support_cases WHERE request_id = %s AND status = 'pending_consent'`
     (idempotente: se já foi promovido, responde 200 com o estado atual em vez
     de duplicar notificação);
   - valida e grava `email` (regex simples) e `display_label` em `customers`
     pelo `customer_id` resolvido — **só se ainda não preenchidos** (não
     sobrescreve dado existente sem necessidade);
   - `UPDATE support_cases SET status='open', customer_id=%s WHERE id=%s`;
   - chama `_enqueue_support_team_notifications` + insere `handoff.requested`
     no outbox (reaproveita literalmente o código que hoje roda inline em
     `record_chat`, só que a partir daqui);
   - devolve o payload de confirmação (número do ticket, tema, data/hora,
     `context_snapshot_sanitized`) para o widget renderizar a mensagem final.
8. Widget renderiza a confirmação do ticket como uma mensagem especial (não é
   resposta do LLM).

**Timeout/abandono:** se o cliente não completar o passo 4 (OTP) dentro de 15
min, o job do §6 dispara o lembrete. Se abandonar antes do passo 3 (nunca
informou telefone), **não existe canal para lembrete proativo** — não há
`otp_challenges` row, não há telefone. Isso é aceitável e deve ficar documentado
como limite conhecido, não bug: sem telefone, não tem por onde mandar nada.

---

## 5. Contrato do novo endpoint

```
POST /web/handoff/consent
Auth: sessão web já autenticada (cookie web:<uuid> vinculado a verified_identity)
Body: { "request_id": "<uuid>", "name": "<string, 1-120 chars>", "email": "<string, formato basico>" }

200 OK
{ "support_case_id": "<uuid>", "status": "open", "opened_at": "<iso>",
  "summary": "<string>", "domain": "<string>" }

401 Unauthorized  -- sessão não autenticada (sem verified_identity)
404 Not Found     -- request_id não corresponde a support_case pending_consent do customer_id da sessão
422 Unprocessable -- nome/e-mail invalidos
```

Regra de posse: o `support_case` encontrado por `request_id` só pode ser
promovido se `support_cases.customer_id IS NULL` (ainda não promovido) **ou**
já é igual ao `customer_id` da sessão atual — impede que a sessão A promova um
`request_id` que pertence à conversa da sessão B (não deveria acontecer no fluxo
normal, mas fecha a superfície de abuso caso alguém adivinhe/reutilize um
`request_id`, que já é exposto ao cliente como "código de suporte").

---

## 6. Job de lembrete de 15 minutos

**Onde escanear:** `otp_challenges`, não `support_cases`. É lá que mora o
telefone (via `phone_hash`/`identity_candidate_hash`) e é o desafio, não o
ticket, que precisa ser completado.

```sql
SELECT id, identity_candidate_hash, phone_last4
FROM otp_challenges
WHERE status IN ('pending', 'expired')
  AND created_at < now() - interval '15 minutes'
  AND created_at > now() - interval '2 hours'   -- não reviver tentativas antigas
  AND reminder_sent_at IS NULL
```

Para cada linha:
1. Gera um **desafio novo** (o TTL padrão de OTP é `OTP_CODE_TTL_SECONDS=300` =
   5 min — **menor que os 15 min do lembrete**, então o desafio original quase
   certamente já expirou; nunca tentar reenviar o código morto).
2. Entrega pelo mesmo transporte configurado (`WEB_AUTH_OTP_DELIVERY_TRANSPORT`),
   mas **via outbox** (`operational_outbox`, evento novo
   `otp.reminder.requested`), não com chamada síncrona direta ao provider — ver
   §7 (reaproveitamento).
3. Marca `otp_challenges.reminder_sent_at = now()` na linha original (idempotência
   do job: rodar 2x não manda 2 lembretes).

**Risco concreto de rate limit (achado ao ler o código):**
`OTP_START_LIMIT_PER_PHONE_PER_15_MINUTES` tem default **3**. Se o cliente já
tentou reenviar manualmente (1 slot) e o job soma outro (2º slot), sobra pouca
margem. O job **não pode** chamar `WebWhatsAppAuthService.start()` como está
hoje (ele passa pelo `_phone_limiter` do cliente) — precisa de um caminho que
gere o desafio sem consumir o mesmo orçamento de rate limit do usuário (ex.: um
método `start_system_reminder(...)` que pula `_phone_limiter.check()` mas
mantém o `_ip_limiter`/demais proteções irrelevantes aqui). Se o job bater no
limite de qualquer forma, deve logar e pular (nunca derrubar o batch inteiro).

**Agendamento:** systemd timer a cada 5 min (`OnCalendar=*:0/5`), não a cada 15,
para que o atraso entre "completou 15 min" e "lembrete chega" fique pequeno e
previsível — mesmo padrão de granularidade fina + escaneio idempotente já usado
em `dispatch_outbox`.

---

## 7. O que está mal configurado/subaproveitado hoje — oportunidades de reuso

1. **Entrega do lembrete deve passar pelo outbox, não por chamada síncrona.**
   O jeito ingênuo (script chama a API do WhatsApp direto) perde retry,
   idempotência e dead-letter de graça. O projeto já resolveu exatamente esse
   problema para `whatsapp.message.requested` — o job deve **só enfileirar**, e
   deixar `dispatch_outbox` (que já roda como serviço systemd) entregar. Zero
   código novo de entrega.
2. **`InMemoryRateLimiter` já existe e é reutilizável** para qualquer limite novo
   que o endpoint `/web/handoff/consent` precisar (ex.: não deixar promover o
   mesmo `request_id` em loop) — não escrever um limitador novo.
3. **`sanitize_payload`/`context_snapshot_sanitized`** já fazem exatamente o
   trabalho de montar o payload de confirmação do ticket — o endpoint novo só
   precisa ler o que `_upsert_support_case` já gravou, não remontar nada.
4. **Achado de configuração a considerar (não bloqueante):** `OTP_CODE_TTL_SECONDS`
   (5 min) e a janela de lembrete (15 min) hoje não têm nenhuma relação
   configurada entre si — são dois números soltos em `config.py` e no plano.
   Vale documentar explicitamente que o lembrete SEMPRE gera um novo desafio
   (nunca assume que o antigo ainda vale), para não virar bug silencioso se
   algum dia `OTP_CODE_TTL_SECONDS` mudar para um valor pareado com os 15 min.
5. **Índice que vai faltar:** o novo endpoint busca `support_cases` por
   `request_id` — hoje não há índice nessa coluna (só `idempotency_key` é
   `UNIQUE`, que embute `turn_id`, não `request_id`, embora pareado 1:1 na
   prática). Adicionar `CREATE INDEX ix_support_cases_request_id ON
   support_cases(request_id)` na mesma migration 013 evita um scan sequencial
   por lookup — tabela ainda é pequena hoje, mas é grátis resolver agora.
6. **`_enqueue_support_team_notifications` já é uma função isolada e pura o
   suficiente** para ser chamada de um segundo lugar (o novo endpoint) sem
   duplicar lógica — só precisa deixar de estar aninhada implicitamente ao fluxo
   de `record_chat` (hoje é um método privado `self._enqueue...`, chamado só de
   dentro da mesma classe `OperationalRepository`; o novo caminho pode reusar a
   mesma instância/método, já que ambos operam dentro de `OperationalRepository`).

---

## 8. Riscos concretos ("o que pode quebrar")

1. **CRÍTICO — vazamento no support inbox.** Verifiquei
   `app/api/routes/support.py`/`app/support/repository.py`:
   `GET /support/cases` sem `?status=` **devolve todas as linhas**, incluindo
   qualquer status novo. Sem uma mudança explícita, `pending_consent` apareceria
   no inbox do time **antes** do cliente consentir — exatamente o cenário que
   este sprint existe para evitar. Correção obrigatória: quando `status` não é
   passado, o filtro default deve excluir `pending_consent`
   (`status NOT IN ('pending_consent')` ou equivalente), não só validar valores
   permitidos em `_ALLOWED_STATUSES`. Precisa de teste novo em
   `tests/test_support_inbox.py` que prova isso.
2. **Rate limit do reenvio de OTP** (detalhado no §6) — o job de lembrete pode
   ser silenciosamente bloqueado pelo limite de 3/15min por telefone que já
   existe para uso do próprio cliente.
3. **Mensagem de lembrete via Meta Cloud API pode exigir template aprovado.**
   O envio original do OTP já usa `META_WHATSAPP_OTP_TEMPLATE_NAME` (mensagem
   iniciada pela empresa = precisa de template pré-aprovado pela Meta). O
   lembrete é **outra** mensagem iniciada pela empresa (o cliente não respondeu
   nada ainda) — não dá para simplesmente mandar texto livre, quase certamente
   precisa de um **segundo template aprovado** (ou reaproveitar o mesmo, se o
   conteúdo permitir variável). Isso tem lead time de aprovação na Meta —
   **dependência externa a resolver cedo**, não é só código.
4. **Atomicidade preservada, mas com uma janela nova de inconsistência
   aceitável:** entre "caso criado como `pending_consent`" e "promovido para
   `open`", o caso existe no banco mas não gera nenhuma ação visível — isso é
   intencional, mas qualquer relatório/métrica que conte `support_cases` por
   `opened_at` sem filtrar status vai contar casos nunca-consentidos. Vale
   revisar dashboards/queries administrativas existentes (fora do escopo deste
   repo, mas documentar o aviso).
5. **Sessão/cookie precisa sobreviver por todo o fluxo (potencialmente minutos,
   com o lembrete de 15 min).** Se o cliente fechar a aba e abrir de novo, ou o
   cookie expirar/for limpo entre o passo 2 e o passo 6, a correlação
   `request_id → session → customer_id` quebra e o cliente não consegue
   completar o próprio ticket (teria que recomeçar). Não é regressão (o cookie
   já existia), mas a superfície de tempo em que isso importa cresce bastante
   com este sprint. Vale considerar TTL do cookie de sessão web `>=` à janela de
   lembrete mais uma folga.
6. **Frontend não tem nenhuma integração com `/web/auth/*` hoje.** Confirmado
   lendo `app/static/chat/app.js` inteiro: o widget só conhece `/web/chat` e
   `/web/feedback`. Este sprint não é "adicionar um passo" no frontend, é
   **construir do zero** a orquestração de telefone→OTP→nome/e-mail→confirmação
   — é a maior superfície nova do sprint, maior que o backend.
7. **Retry do turno original não deve reverter status.** Confirmado que o
   `ON CONFLICT (idempotency_key) DO UPDATE` de `_upsert_support_case` não
   toca `status` — uma reentrega do mesmo turno escalado não derruba um caso já
   promovido para `open`. Isso já funciona certo por acidente de design; só
   documentar para não ser "corrigido" por engano depois.
8. **Nome/e-mail só perguntados quando ausentes — checar exatamente onde essa
   leitura acontece.** Se o "já tem nome/e-mail?" for decidido só no frontend
   (via `GET /web/auth/session`), existe uma janela de corrida entre duas abas
   do mesmo cliente perguntando ao mesmo tempo — de baixo impacto (pior caso:
   pergunta duas vezes, sobrescreve com o mesmo dado), mas vale um teste.

---

## 9. Crítica ao plano original (Sprint 4b como estava escrito)

- **Maior problema:** "criar o ticket só depois do OTP" quebrava a garantia de
  atomicidade da Sprint 4 sem dizer isso explicitamente — corrigido na §1 deste
  documento (status intermediário + notificação diferida).
- **Faltava mapear o support inbox como consumidor.** O plano original falava
  em "gate no handoff" mas nunca mencionou que existe uma leitura (`GET
  /support/cases`) que precisa ser ensinada sobre o novo status — sem isso o
  gate é furado por um caminho que ninguém ia pensar em testar.
- **Faltava reconhecer que `OTP_CODE_TTL_SECONDS` (5 min) é menor que a janela
  de lembrete (15 min).** O plano dizia "lembra em 15 minutos" sem notar que o
  código original já estaria morto — só ficou explícito ao ler o valor default
  em `config.py`.
- **Faltava o requisito de template da Meta para o lembrete.** Isso é uma
  dependência externa com lead time; se não for identificado agora, vira
  bloqueio de última hora perto do smoke privado.
- **O plano original não distinguia "quem orquestra o fluxo" (frontend vs.
  backend conversacional).** Ficou implícito que seria "conversa natural", mas
  isso exigiria uma máquina de estados nova dentro do `ChatFlowService`
  (equivalente ao hack de `ESCAPE_STATE` do Hermes, que já tem uma fragilidade
  conhecida: o estado de escape ali é checado *antes* de resolver o domínio
  sticky). Recomendo explicitamente **não** repetir esse padrão aqui — a
  orquestração fica no frontend chamando endpoints estruturados existentes
  (`/web/auth/*`) mais um novo (`/web/handoff/consent`), o que é mais simples de
  testar e não introduz um segundo lugar no código com regra de estado
  implícita.
- **Faltava índice/lookup por `request_id`** — pequeno, mas o plano original
  não detalhava como o passo final ("nome/e-mail → ticket sai") ia encontrar o
  caso certo; ficou resolvido reaproveitando uma coluna que já existe.

---

## 10. Fases de execução (menor passo seguro primeiro)

1. **Migration 013** (schema puro, sem código de app) — `customers.email`,
   novo status, colunas de lembrete, índice. Testável isoladamente com
   `python -m scripts.migrate apply` + `verify` num banco descartável.
2. **Gate de criação**: `_upsert_support_case` grava `pending_consent` em vez
   de `open` quando uma flag nova (`ENABLE_HANDOFF_CONSENT_GATE`, default
   `false`) está ligada; **sem** o endpoint novo ainda, então nada promove o
   caso — aceitável em dev/teste, não ligar em produção nesta fase.
3. **Correção do support inbox** (fecha o Risco #1) — pode e deve ir **antes**
   do endpoint novo, com teste dedicado provando que `pending_consent` nunca
   aparece sem filtro explícito.
4. **Endpoint `POST /web/handoff/consent`** + `promote_pending_case` +
   reaproveitamento de `_enqueue_support_team_notifications`.
5. **Job de lembrete** (`scripts/remind_pending_otp.py`) + timer systemd,
   dark por flag até o smoke.
6. **Frontend**: telefone → OTP → nome/e-mail → confirmação. Maior fatia,
   pode ser dividida em sub-passos (UI de telefone/OTP primeiro, reaproveitando
   endpoints já testados no backend; nome/e-mail depois).
7. **Ligar `ENABLE_HANDOFF_CONSENT_GATE` em staging** só depois de 1-6 + smoke
   manual do fluxo completo (incluindo o cenário de abandono/lembrete).

---

## 11. Testes necessários

- `tests/test_web_handoff.py` (novo): endpoint 200/401/404/422, idempotência
  (chamar 2x não duplica notificação), regra de posse (`customer_id` não bate).
- `tests/test_support_inbox.py` (estender): sem filtro nunca retorna
  `pending_consent`; filtro explícito `?status=pending_consent` funciona para
  quem precisa depurar.
- `tests/test_handoff.py`/testes de `operational.py`: `_upsert_support_case`
  grava `pending_consent` com a flag ligada, `open` com a flag desligada
  (comportamento legado inalterado).
- Novo teste para o job de lembrete: fake clock, desafio > 15 min sem
  `reminder_sent_at` gera evento no outbox; desafio já lembrado não duplica;
  desafio > 2h é ignorado (bound window).
- Integração gated (Postgres real): migration 013 aplica limpo; fluxo
  ponta-a-ponta criar caso → promover → aparecer no inbox só depois.
- `python -m app.evals.run_domain_eval suporte-vps-whatsapp` — não deveria
  mudar comportamento de resposta (o gate é só no handoff), mas roda por
  disciplina já que toca `ChatFlowService`/`handoff` indiretamente.

---

## 12. Perguntas em aberto (para decidir antes da fase 6/7)

- Template da Meta para o lembrete: reaproveitar o mesmo do OTP inicial (se o
  conteúdo permitir variável) ou provisionar um segundo? Tem lead time de
  aprovação — vale iniciar essa conversa com a Meta cedo, em paralelo ao
  código.
- TTL do cookie de sessão web hoje é suficiente para cobrir a janela de
  lembrete + folga, ou precisa aumentar?
