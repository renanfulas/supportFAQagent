# Plano técnico — gate de consentimento LGPD no handoff (Sprint 4b)

Plano de execução detalhado, em nível de arquivo/classe/endpoint/migration, para
implementar o Sprint 4b registrado em
[`customer-identity-whatsapp-handoff-plan.md`](./customer-identity-whatsapp-handoff-plan.md).
Este documento é o "como"; o outro é o "o quê / por quê". Revisão: 2026-07-01.

**Status: implementado (2026-07-01).** Fases 1–5 abaixo concluídas, com um
desvio real em relação ao §6 original (job de lembrete no backend) — corrigido
para lembrete client-side ao longo da implementação; ver nota em §6. Sem
Postgres real disponível nesta sessão, então os testes de integração gated
(`tests/integration/test_phase0_postgres.py`) foram escritos e compilam, mas
não foram executados contra banco real aqui — vão rodar no harness/CI que já
tem Postgres. O restante (unitários, endpoint, frontend) foi validado
diretamente, incluindo verificação manual no navegador do fluxo completo.

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
| Migration | `migrations/013_customer_contact_and_consent.sql` | `customers.email`; `support_cases_status_check` ganha `'pending_consent'` (sem colunas de lembrete — ver §6) |
| Config | `app/core/config.py` | `ENABLE_HANDOFF_CONSENT_GATE` (default off, exige `enable_web_whatsapp_auth`) + `OTP_ABANDONMENT_REMINDER_MINUTES` (default 15) |
| Backend — criação do caso | `app/db/operational.py::record_chat`/`_upsert_support_case` | passa `status='pending_consent'` quando o gate está ativo e `channel='web'`; **não** chama `_enqueue_support_team_notifications`/insere `handoff.requested` nesse caminho |
| Backend — novo endpoint | `app/api/routes/web_handoff.py` | `POST /web/handoff/consent` — recebe `request_id`+nome+e-mail, exige sessão já autenticada (`CurrentIdentityResolver`), promove o caso |
| Backend — lógica de negócio | `app/db/operational.py::OperationalRepository.promote_pending_consent` | valida ownership, grava nome/e-mail em `customers` (só se ausentes), muda status→`open`, enfileira outbox + notificação (reaproveita `_enqueue_support_team_notifications`); idempotente |
| Backend — leitura (inbox) | `app/support/repository.py::list_cases`, `app/api/routes/support.py` | corrigido: sem filtro explícito de status, `pending_consent` nunca aparece; `?status=pending_consent` explícito funciona |
| Backend — schema contract | `app/db/schema_contract.py` | novo `email` em `customers`, novo status em `support_cases`; `CONTRACT_MIGRATION` avançado para `013_` |
| Backend — lembrete de OTP | **sem job novo** — `abandonment_reminder_seconds` no response de `/web/auth/whatsapp/start` + lógica 100% no widget (ver §6, corrigido) | |
| Backend — OTP (reaproveitado sem mudança de contrato) | `app/web_auth/service.py`, `app/web_auth/storage.py`, `app/api/routes/web_auth.py` | `start`/`confirm`/`session` seguem iguais, só ganhou o campo novo no response do `start` |
| Frontend | `app/static/chat/app.js`, `styles.css` | implementado: convite → telefone → OTP (com lembrete local) → nome/e-mail → confirmação do ticket |
| Docs | `docs/architecture/integration-contracts.md` | contrato `POST /web/handoff/consent` documentado, seção do inbox atualizada |
| Testes | `tests/test_web_handoff.py`, `tests/test_support_inbox.py`, `tests/test_phase0_operational_safety.py`, `tests/test_web_auth.py`, `tests/integration/test_phase0_postgres.py` (gated) | todos passando (668 passed, 35 skipped incl. os gated) |

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

```

Nota: `support_cases_closed_at_check` já cobre `pending_consent` sem alteração
(cai no ramo "não fechado" existente) — só a constraint de `status` precisa de
drop+recreate (Postgres não altera `CHECK` in-place).

**Correção (2026-07-01):** as colunas `consent_reminder_sent_at`/
`reminder_sent_at` planejadas aqui para um job de lembrete **foram removidas**
antes da migration ser aplicada em qualquer ambiente — o job em si acabou
descartado (ver §6, achado de privacidade). A migration final tem só as duas
mudanças acima (`customers.email` + status `pending_consent`).

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

## 6. Lembrete de abandono do OTP — corrigido durante a implementação

**O desenho original deste documento (job de backend escaneando
`otp_challenges` a cada 5 min) não foi implementado — é irrealizável.**
Achado ao tentar construir: `otp_challenges.identity_candidate_hash` é
`HMAC(telefone)`, irreversível por design (`migrations/002_web_auth.sql`:
*"phone_e164 nunca persiste nessas tabelas"*). Um job assíncrono rodando 15
min depois **não tem para onde reenviar** — não existe, em nenhum lugar do
sistema, o telefone bruto guardado durável o suficiente para isso. Guardar o
telefone (mesmo criptografado) só para viabilizar esse job quebraria essa
regra não-negociável do projeto.

**Desenho final: lembrete client-side, sem job novo.**
`POST /web/auth/whatsapp/start` passou a devolver `abandonment_reminder_seconds`
(`app/api/schemas/web_auth.py`, populado a partir de
`settings.otp_abandonment_reminder_minutes * 60`). O widget
(`app/static/chat/app.js::renderOtpForm`) arma um `setTimeout` local com esse
valor; se estourar antes do `confirm` ter sucesso, mostra "ainda não recebeu?"
e um botão que reusa o mesmo fluxo de `renderPhoneForm` (novo `start`, novo
`challenge_id`) — sem endpoint novo, sem dado sensível novo em repouso, sem
systemd timer.

**Limitação aceita, não é bug:** se o cliente fechar a aba antes dos 15 min,
não há como avisá-lo — não existe canal para isso sem guardar o telefone. Os
achados de rate-limit (`OTP_START_LIMIT_PER_PHONE_PER_15_MINUTES=3`) e de TTL
(`OTP_CODE_TTL_SECONDS=300` < janela de lembrete) continuam válidos e
relevantes aqui: o botão de "reenviar" do widget é exatamente um novo `start`,
então consome o mesmo rate limit de qualquer reenvio manual — isso é aceitável
porque agora é uma ação explícita do cliente clicando, não um job automático
tentando silenciosamente e podendo ser bloqueado sem ninguém perceber.

Migration 013 não ganhou as colunas `reminder_sent_at`/`consent_reminder_sent_at`
que este documento planejava (ver correção na §3) — não há mais o que marcar,
pois não há job.

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

1. **CRÍTICO — vazamento no support inbox. Corrigido.** Verifiquei
   `app/api/routes/support.py`/`app/support/repository.py`:
   `GET /support/cases` sem `?status=` **devolvia todas as linhas**, incluindo
   qualquer status novo. Sem a correção, `pending_consent` apareceria no inbox
   do time **antes** do cliente consentir — exatamente o cenário que este
   sprint existe para evitar. Corrigido em `list_cases`: sem `status` explícito,
   `pending_consent` é excluído por padrão; `?status=pending_consent` explícito
   continua funcionando. Testes em `tests/test_support_inbox.py`.
2. **Rate limit do reenvio de OTP — não é mais risco de job, é risco de UX
   normal.** Como não existe mais job de backend (§6, corrigido), este risco
   virou apenas: um cliente clicando "reenviar" repetidamente no widget pode
   bater no limite de 3/15min por telefone — comportamento esperado e já
   coberto pelo erro `429 too_many_requests` que o widget trata.
3. ~~Mensagem de lembrete via Meta Cloud API pode exigir template aprovado~~ —
   **não se aplica mais**: não há mensagem de lembrete proativa via WhatsApp;
   o lembrete é só uma UI local no widget (§6, corrigido).
4. **Atomicidade preservada, mas com uma janela nova de inconsistência
   aceitável:** entre "caso criado como `pending_consent`" e "promovido para
   `open`", o caso existe no banco mas não gera nenhuma ação visível — isso é
   intencional, mas qualquer relatório/métrica que conte `support_cases` por
   `opened_at` sem filtrar status vai contar casos nunca-consentidos. Vale
   revisar dashboards/queries administrativas existentes (fora do escopo deste
   repo, mas documentar o aviso).
5. **Sessão/cookie precisa sobreviver por todo o fluxo.** Se o cliente fechar
   a aba e abrir de novo, ou o cookie expirar/for limpo no meio do fluxo, a
   correlação `request_id → session → customer_id` quebra e ele não consegue
   completar o próprio ticket (teria que recomeçar). Não é regressão (o cookie
   já existia), mas a superfície de tempo em que isso importa cresce com este
   sprint. Ainda assim, sem o lembrete server-push, o pior caso é limitado ao
   tempo que o cliente realmente fica na página — não é mais uma janela de
   até 15+ min esperando um push que talvez nunca chegue.
6. **Frontend não tinha nenhuma integração com `/web/auth/*` — implementado.**
   Confirmado lendo `app/static/chat/app.js` inteiro antes de começar: o widget
   só conhecia `/web/chat` e `/web/feedback`. Era a maior superfície nova do
   sprint, maior que o backend — construída do zero
   (`renderConsentPrompt`/`renderPhoneForm`/`renderOtpForm`/`renderContactForm`/
   `buildTicketConfirmation`), verificada manualmente no navegador ponta a
   ponta.
7. **Retry do turno original não deve reverter status.** Confirmado que o
   `ON CONFLICT (idempotency_key) DO UPDATE` de `_upsert_support_case` não
   toca `status` — uma reentrega do mesmo turno escalado não derruba um caso já
   promovido para `open`. Isso já funciona certo por acidente de design; só
   documentar para não ser "corrigido" por engano depois.
8. **Nome/e-mail — decisão de escopo tomada durante a implementação.** Em vez
   de o frontend decidir "já tem nome/e-mail?" via `GET /web/auth/session`
   antes de mostrar o formulário (que exigiria expor esses campos nesse
   endpoint, e abriria a janela de corrida entre abas descrita originalmente
   aqui), o widget **sempre** mostra o formulário de contato depois do OTP
   confirmar. O backend (`promote_pending_consent`) já protege com `COALESCE`
   — se o cliente já tinha nome/e-mail salvos, o reenvio é ignorado
   silenciosamente. Simplifica o frontend e elimina a corrida; custo aceito:
   um cliente recorrente pode digitar de novo um dado que já tinha informado.

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

## 10. Fases de execução — todas concluídas (2026-07-01)

1. ✅ **Migration 013** — `customers.email` + status `pending_consent` (sem
   colunas de lembrete, ver §6). `schema_contract.py` atualizado,
   `CONTRACT_MIGRATION` avançado.
2. ✅ **Gate de criação**: `_upsert_support_case` grava `pending_consent`
   quando `ENABLE_HANDOFF_CONSENT_GATE=true` e `channel='web'`.
3. ✅ **Correção do support inbox** (fecha o Risco #1) — feita antes do
   endpoint, com testes dedicados.
4. ✅ **Endpoint `POST /web/handoff/consent`** + `promote_pending_consent` +
   reaproveitamento de `_enqueue_support_team_notifications`.
5. ~~Job de lembrete~~ **não construído — corrigido para lembrete client-side**
   (ver §6). Sem script, sem timer systemd.
6. ✅ **Frontend**: telefone → OTP (com lembrete local) → nome/e-mail →
   confirmação. Verificado manualmente no navegador (fluxo completo, incluindo
   o caminho de erro gracioso sem Postgres disponível).
7. ✅ **Ligado e validado em staging (2026-07-01)**: migration 013 aplicada na
   VPS, `ENABLE_HANDOFF_CONSENT_GATE=true`, smoke manual real completo —
   escalação → `pending_consent` (invisível no inbox sem filtro) → 401 sem
   OTP → OTP real via WhatsApp/Hermes → consent promove para `open` +
   `handoff.requested` enfileirado na mesma transação (timestamps idênticos) →
   consent repetido idempotente → case visível no inbox como `open`.

---

## 11. Testes necessários — status

- ✅ `tests/test_web_handoff.py`: endpoint 404 (gate off), 401 (sem OTP), 422
  (campo extra). Cobertura de 200/idempotência/posse fica em
  `tests/test_phase0_operational_safety.py` (unit, via `promote_pending_consent`
  direto) e `tests/integration/test_phase0_postgres.py` (ponta-a-ponta, gated).
- ✅ `tests/test_support_inbox.py`: sem filtro nunca retorna `pending_consent`;
  filtro explícito `?status=pending_consent` funciona.
- ✅ `tests/test_phase0_operational_safety.py`: `_upsert_support_case` grava
  `pending_consent` com a flag ligada e canal `web`; `open` com a flag
  desligada ou canal diferente de `web` (WhatsApp nativo inalterado);
  `promote_pending_consent` (happy path, idempotência, not-found, ownership
  mismatch, email inválido).
- ~~Teste do job de lembrete~~ não se aplica (não há job).
- ✅ Integração gated (`tests/integration/test_phase0_postgres.py`, escrita e
  compila, não executada nesta sessão por falta de Postgres local): migration
  013 aplica limpo; fluxo ponta-a-ponta criar caso → promover → aparecer no
  inbox só depois → nome/e-mail persistidos → reenvio não duplica notificação.
- ✅ `python -m app.evals.run_domain_eval suporte-vps-whatsapp`: rodado em
  2026-07-01 **na própria VPS de staging** (chave real + pgvector real, a
  configuração exata de produção) com **0 falhas** — pendência quitada.

---

## 12. Perguntas em aberto

- ~~Template da Meta para o lembrete~~ **não se aplica mais** — não há mais
  mensagem de lembrete proativa via WhatsApp (§6, corrigido).
- ~~TTL do cookie vs. janela de lembrete~~ menos crítico agora que o lembrete é
  local e não depende de um push chegando depois de o cliente já ter saído —
  ainda vale considerar se o TTL do cookie cobre confortavelmente o tempo
  típico do fluxo completo (telefone → OTP → nome/e-mail), mas não é mais um
  requisito duro de "minutos até um push chegar".
- ~~Rodar `run_domain_eval` com chave real antes de ligar a flag~~ — feito em
  2026-07-01 na VPS (chave real + pgvector), 0 falhas.
- ~~Smoke real em staging (Postgres + WhatsApp de verdade)~~ — feito em
  2026-07-01; evidências registradas na seção do Sprint 4b em
  [`customer-identity-whatsapp-handoff-plan.md`](./customer-identity-whatsapp-handoff-plan.md)
  e no §10 acima. A frente está validada contra infraestrutura real.
