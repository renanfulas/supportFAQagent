# Plano Tecnico - Ponte WhatsApp <-> Console (Atendimento Humano por Numero de Suporte)

Status: proposto em 2026-07-04; **Fase 1 implementada em codigo em 2026-07-05**
(migrations 016/017/018, cifra/token em `app/support/wa_binding.py`, handler de
inbound e compositor em `app/support/whatsapp_bridge.py`, roteamento por
`phone_number_id` no webhook Meta, deep link no handoff, dispatcher com
selecao de numero e status de entrega, readiness `whatsapp_bridge`, suite de
testes; 839 testes verdes, `compileall` limpo). **Fase 2 implementada em
codigo em 2026-07-05** (mesmo dia): `whatsapp.template.requested` +
`email.message.requested` no outbox (a rota de e-mail fica com transporte
`disabled` de proposito -- nenhum provedor foi decidido; Juliano liga so
trocando `OUTBOX_EMAIL_DELIVERY_TRANSPORT`, sem mudar codigo), compositor
aceita `template` opcional para responder fora da janela
(`ALLOWED_STAFF_TEMPLATES = {precisa_info, reengajar}`), notificacao proativa
em `app/support/transitions.py` para `claim` (-> `atendente_assumiu`) e
`close` (-> `ticket_resolvido`, com resumo), renderer puro em
`app/notifications/customer_status.py`, opt-out de e-mail em
`app/support/customer_preferences.py` (default opt-in; le
`customer_preferences` global). Sem migration nova (reusa
`case_whatsapp_bindings`, `customer_preferences`, `operational_outbox`);
856 testes verdes. Contrato registrado em
`docs/architecture/integration-contracts.md` ("Ponte WhatsApp<->console"),
smoke em `docs/runbooks/whatsapp-support-bridge-smoke.md`. **Dark por padrao**
(`ENABLE_WHATSAPP_SUPPORT_NUMBER=false`) -- falta o provisionamento externo na
Meta (Juliano: numero de suporte + webhook + aprovacao dos 4 templates) para o
smoke real e a promocao a staging/producao, e o transporte de e-mail (Juliano,
provedor ainda nao decidido). Fase 3 (unificacao de identidade) permanece nao
iniciada, opcional.
E a implementacao do degrau 3 ("fechar o ciclo com o cliente") da visao V3 do
[web-chat-evolution-plan.md](web-chat-evolution-plan.md), do lado da conversa
humana. Complementa e **revisa** a conclusao "so e-mail" da Fase C do
[web-chat-customer-ticket-status-tech-plan.md](web-chat-customer-ticket-status-tech-plan.md)
(ver secao "Fronteira de privacidade"). Consome o console do time
([support-team-console-tech-plan.md](support-team-console-tech-plan.md)) como
posto de trabalho do atendente.

## Tese De Produto

O console web e o **posto de trabalho do atendente**; o WhatsApp e a **superficie
do cliente**. Um helpdesk com WhatsApp por tras: o time organiza e responde no
web, o cliente vive no WhatsApp e nao ve o console.

- **Cliente (WhatsApp)**: andamento do ticket, resumo do que foi conversado,
  e-mail — tudo pelo canal que ele prefere.
- **Atendente (console web)**: tudo isso + a conversa que ele digita e que sai
  no WhatsApp do cliente.

Decisoes fechadas no brainstorm que este plano materializa:

1. **Dois numeros**: numero padrao (bot, Hermes por enquanto) e numero de
   suporte (humano via console, Meta-nativo).
2. **Desenhar para as regras da Meta desde ja** (janela de 24h + templates),
   mesmo o Hermes nao as impondo hoje.
3. **Modo por numero**: no numero de suporte nao roda RAG — inbound ali e sempre
   "canal humano". Isso elimina a corrida bot-vs-humano quase de graca.
4. **Numero de suporte e handoff-only** (privado, alcancado so via handoff), o
   que garante que sempre existe ticket + contexto — sem triagem.

## Decisao Arquitetural

```text
                    numero PADRAO (bot)                 numero SUPORTE (humano)
                    Hermes/Baileys (hoje)               Meta Cloud API (oficial)
Cliente WhatsApp  ----->  RAG + roteador + stickiness      ----->  sem RAG
                            |  handoff: deep link -------------------^  |
                            v                                           v
                       support_case (ja existe)  <----  bind por phone_hash
                            |                                           |
Atendente  <----  Console /web/support/* (fila, detalhe, transicoes)   |
                            |  compositor novo                         |
                            +----> outbox whatsapp.message/template ---+--> WhatsApp do cliente
```

Principios herdados: nada de canal paralelo de dados, nenhum segredo no browser,
o backend continua dono da inteligencia (o transporte so entrega).

**Por que o numero de suporte nasce Meta-nativo, nao numa segunda ponte Hermes:**

- O Hermes e Baileys (WhatsApp **nao-oficial**) e **segura uma sessao por
  bridge** (`bridge.js`, verificado em
  [hermes-chat-bridge-plan.md](hermes-chat-bridge-plan.md)). Um segundo numero =
  segunda instancia Baileys (outro processo/porta/QR), mais fragil, com risco de
  ban proprio — e o proprio plano do Hermes ja recomenda "numero dedicado".
- No Meta Cloud API, multiplos numeros sob a mesma WABA e **nativo** (varios
  phone number IDs), e e la que existem **template e janela de 24h**.
- Poe o que importa (atendimento humano + comunicacao proativa) no trilho
  **confiavel e oficial**, deixando o numero bot no Hermes como ponte temporaria
  ate a migracao Meta do proprio bot.

## Regras Da Meta Que Desenhamos Desde Ja

A janela de 24h (customer service window): apos uma mensagem do cliente, a
empresa pode enviar **free-form** por 24h; cada nova mensagem do cliente
**reabre** a janela. Fora dela, so **template aprovado** (categoria utility para
atualizacao de ticket).

Como isso quase nunca vira parede:

- **Conversa viva se mantem aberta sozinha.** No atendimento ativo, o cliente
  responde e reabre a janela; o atendente responde em minutos/horas. Free-form,
  sem template.
- **A parede so aparece no silencio > 24h** (avisar status depois que o cliente
  sumiu). Ai entra um **template utility** com botao; o cliente toca -> vira
  inbound -> **reabre a janela** -> atendente volta ao free-form.
- **O deep link e o toque do cliente sao abridores de janela**: o "bot fino" so
  fala free-form depois que o cliente inicia.

Templates utility iniciais (~4; copy/parametros finalizados com a WABA — Juliano).
**Pre-condicao: template so e possivel para quem ja temos o `wa_id`** (o cliente
ja mandou ao menos uma mensagem no numero de suporte). Antes disso nao existe
numero pra enviar — ver a nota de primeiro contato.

| Template | Quando | Botao |
| --- | --- | --- |
| `atendente_assumiu` | transicao `-> in_progress` fora de janela | "Responder" |
| `precisa_info` | atendente precisa de dado e cliente sumiu > 24h | "Responder" |
| `ticket_resolvido` | transicao `-> closed` fora de janela (+ resumo) | "Reabrir" |
| `reengajar` | reabrir contato apos silencio longo | "Continuar" |

**Primeiro contato difere por origem** (nao ha template uniforme de "ticket
recebido"):

- **web-origin**: o primeiro contato e o **deep link no widget web** — nao um
  template WhatsApp, porque ainda nao temos o numero. So depois que ele toca e
  manda a primeira mensagem e que os templates passam a valer.
- **native-origin**: o primeiro contato e o deep link **na thread do numero bot**
  (ali ja temos como falar com ele), levando ao numero de suporte.

O backend decide free-form vs template no envio: se `now - last_customer_message_at
< 24h` -> evento free-form; senao -> evento de template.

**Custo:** conversa dentro da janela (service, free-form) e **gratis** (Meta,
desde nov/2024); **template utility custa por mensagem**. Isso reforca "ficar na
janela" como decisao de **custo**, nao so de UX — o volume de templates proativos
vira metrica operacional a acompanhar.

## Fronteira De Privacidade (A Decisao Central)

Para o atendente responder do console **de forma assincrona** (minutos/horas
depois), o backend precisa do identificador WhatsApp do cliente (`wa_id`, que e o
E.164) para enviar — o webhook de inbound entrega o `wa_id`, mas a resposta sai
fora daquela request. **Logo, atendimento console<->WhatsApp exige guardar o
numero do cliente.** Isso contradiz a disciplina atual de "so `phone_hash` +
`phone_last4`, nunca telefone bruto".

**Decisao (fechada 2026-07-04): Opcao A — guardar o `wa_id` cifrado, escopado ao
caso, com retencao dupla.** E necessidade da frente: sem o numero em repouso nao
existe resposta assincrona do atendente nem notificacao proativa (o ponto todo).
A Opcao B (nao guardar, so sincrono/pull) foi **descartada** — inviabiliza a
frente.

- Cifra simetrica autenticada (AES-GCM ou Fernet), chave dedicada
  `SUPPORT_WA_ENC_KEY` (nunca reusar `IDENTITY_HASH_SECRET`); **decifra apenas no
  caminho de envio**, nunca em log/leitura geral.
- Vive numa tabela propria (`case_whatsapp_bindings`), separada do caso duravel.
- **Retencao dupla (o que vier primeiro):** apagado **quando o caso fecha/cancela**
  **ou** apos **15 dias** sem resolucao (`bound_at + SUPPORT_WA_BINDING_MAX_DAYS`).
  Um caso parado 15 dias perde o numero; se o cliente voltar, ele reabre a janela
  e o vinculo e refeito pelo token. Retencao minima, finalidade clara.
- Base legal LGPD: necessario para o atendimento que o cliente pediu e consentiu;
  minimizado (so `wa_id`), cifrado e temporario com teto explicito.

Isso **revisa** a conclusao da Fase C do customer-ticket-status ("so e-mail,
porque nao guardamos telefone"): com o armazenamento cifrado, escopado e com teto
de 15 dias, o WhatsApp volta a ser canal viavel — e o e-mail continua como canal
paralelo (`customers.email`, ja legivel/consentido) para quem opta ou nao tem
thread ativa.

Consentimento: o gate LGPD (Sprint 4b) ja cobre "contato direto da equipe"; a
copy do consent passa a ser explicita sobre "vamos te atender pelo WhatsApp e
guardar seu numero **ate o atendimento fechar, no maximo 15 dias**".

## Vinculo De Identidade (Cliente -> Thread De Suporte)

Todo atendimento humano acontece **no numero de suporte** (superficie humana
unica). No handoff, o cliente recebe um **deep link** `wa.me/<suporte>?text=...`
com um **token de caso** curto e opaco (assinado/armazenado, escopado ao caso) no
texto pre-preenchido. **O token e o mecanismo primario de vinculo — nao o hash do
telefone.**

- **Web-origin** (deep link no widget web): nao temos o telefone bruto ate ele
  tocar o link. A primeira mensagem no numero de suporte chega com o token; o
  backend resolve `token -> caso` e so entao guarda o `wa_id` (que o transporte
  entrega) cifrado. **Nao** dependemos de casar `phone_hash` com
  `verified_identities` — o cliente pode ate mandar de um WhatsApp diferente do
  numero que digitou no OTP.
- **Native-origin** (veio pelo numero bot): o bot manda o deep link; o cliente
  toca e continua no numero de suporte. Aqui o token e ainda **mais** necessario,
  porque o caso native provavelmente **nao tem `customer_id`** (a frente de
  identidade decidiu que WhatsApp nativo se apoia em hash de sessao, nao em Auth)
  — logo `phone_hash -> customer_id -> caso` simplesmente nao existe. Custo: uma
  troca de numero (thread nova no app dele); mitigacao: copy clara + um clique, e
  o ganho de manter o atendimento humano **fora** do numero Hermes (nao-oficial).

O `phone_hash` entra so como **conferencia opcional** (quando ha
`verified_identity`), nunca como o vinculo em si. Token invalido/ausente cai num
fluxo de erro amigavel ("nao encontrei seu atendimento, toque no link do seu
chamado"), nunca vincula ao caso errado.

Resolvido o token, o `wa_id` cifrado entra em `case_whatsapp_bindings` e as
mensagens da thread passam a anexar na conversa **daquele caso** (canal
`whatsapp_support`), preservando o transcript unico do console.

Unificacao plena de historico (a conversa pre-handoff do numero bot + a thread de
suporte como uma timeline so por `customer_id`) reaproveita esse casamento por
hash, mas a reconciliacao dos dois dominios de hash (web `IDENTITY_HASH_SECRET`
vs sessao WhatsApp) fica como **Fase 3 opcional** (decisao adiada de proposito na
frente de identidade).

## Modelo De Dados (migrations aditivas)

### Migration 016 - binding da thread de suporte

```sql
CREATE TABLE case_whatsapp_bindings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id UUID NOT NULL REFERENCES support_cases(id) ON DELETE CASCADE,
  wa_id_encrypted BYTEA NOT NULL,        -- E.164 cifrado (AES-GCM/Fernet)
  last_customer_message_at TIMESTAMPTZ,  -- janela de 24h
  bound_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,       -- bound_at + SUPPORT_WA_BINDING_MAX_DAYS (15d)
  unbound_at TIMESTAMPTZ,                -- setado no fechamento/purga
  CONSTRAINT case_whatsapp_bindings_case_unique UNIQUE (case_id)
);
CREATE INDEX idx_case_wa_bindings_open
  ON case_whatsapp_bindings (case_id) WHERE unbound_at IS NULL;
CREATE INDEX idx_case_wa_bindings_expiry
  ON case_whatsapp_bindings (expires_at) WHERE unbound_at IS NULL;
```

Purga (retencao dupla, o que vier primeiro): no **fechamento/cancelamento** do
caso **ou** quando `now() > expires_at` (15 dias sem resolucao). O fechamento
zera na hora; um **job periodico** varre `expires_at` (indice
`idx_case_wa_bindings_expiry`) e apaga `wa_id_encrypted`, marcando `unbound_at`.
Depois disso, se o cliente voltar, o token do deep link refaz o vinculo.

### Migration 017 - ator generico nos eventos

`support_case_events.actor_staff_id` e hoje `NOT NULL` (migration 015,
staff-only). Para registrar mensagem/resposta do cliente e acoes do sistema na
mesma trilha:

```sql
ALTER TABLE support_case_events
  ALTER COLUMN actor_staff_id DROP NOT NULL,
  ADD COLUMN actor_kind TEXT NOT NULL DEFAULT 'staff'
    CHECK (actor_kind IN ('staff','customer','system')),
  ADD COLUMN actor_customer_id UUID REFERENCES customers(id);
-- CHECK: exatamente um ator conforme actor_kind (staff -> staff_id; customer -> customer_id; system -> nenhum)
```

**Impacto no console (obrigatorio):** `get_case_events`
([repository.py](../../app/support/repository.py)) faz hoje um **INNER JOIN**
`staff_members ON e.actor_staff_id`. Com a coluna nullable, eventos
`actor_kind='customer'/'system'` (staff_id NULL) **sumiriam** da trilha exibida.
A 017 exige trocar por **LEFT JOIN** e projetar o ator conforme `actor_kind`
(atendente -> `display_name`; cliente -> "Cliente"; sistema -> "Sistema"). Sem
isso, o historico do console fica incompleto em silencio.

### `messages` - canais

`channel` e **TEXT livre** (migration 006, sem CHECK), entao `whatsapp_support`
(thread de suporte) **nao precisa de migration** — so contrato. A role `agent`
(atendente humano, distinta de `assistant`/bot) **precisa de verificacao**: se
`role` tiver CHECK, entra na 017; se for livre, so contrato. Confirmar antes da
Fase 1.

### `schema_contract.py`

Objetos das 016/017 entram em `REQUIRED_*` para a guarda de schema cobrir a
frente como cobre o resto.

## Contratos E Fluxos

### Inbound no numero de suporte (Meta webhook)

`app/integrations/meta_whatsapp/webhook.py` roteia por phone number ID: inbound
no ID do numero de suporte -> handler novo (nao o fluxo RAG):

1. resolve `wa_id` -> `HMAC` -> `verified_identities.phone_hash` -> `customer_id`
   -> caso aberto (ou pelo token do deep link);
2. anexa `messages(role='user', channel='whatsapp_support')` na conversa do caso;
3. atualiza `case_whatsapp_bindings.last_customer_message_at` (reabre a janela);
4. registra `support_case_events(actor_kind='customer', ...)`;
5. **thin bot** (unico automatismo): se o caso ainda nao tem atendente / primeiro
   contato -> ack ("recebemos, um atendente responde por aqui"); fora do horario
   -> mensagem de horario. Tudo free-form (a janela acabou de abrir). Sem RAG,
   sem triagem.

### Compositor do atendente (console)

`POST /web/support/cases/{case_id}/message` (auth staff `require_staff_session` +
CSRF `X-Requested-With`):

- body `{ "message": "..." }`;
- grava `messages(role='agent', channel='whatsapp_support', actor=staff)` na
  conversa do caso, na mesma transacao;
- decide o envio: janela aberta -> enfileira `whatsapp.message.requested`
  (free-form) para o `wa_id` decifrado; janela fechada (> 24h) -> `409
  window_closed` com a lista de templates disponiveis (a UI oferece enviar um
  template utility em vez de free-form);
- reaproveita o outbox + dispatcher ja usados pela notificacao ao time (Sprint 5);
- **status de entrega (obrigatorio para chat):** cada mensagem do atendente
  guarda estado (`queued -> sent -> delivered -> read -> failed`) atualizado pelos
  callbacks de status da Cloud API, exibido por mensagem no console. Sem isso o
  atendente nao sabe se o cliente recebeu;
- **a janela e autoritativa na Meta, nao aqui:** nosso `last_customer_message_at`
  e um espelho best-effort. Um free-form pode ser **recusado** pela Meta mesmo com
  a janela parecendo aberta (drift / mensagem nao vista). Nesse caso o dispatcher
  cai para o template `reengajar` e marca a mensagem como `failed` com motivo,
  visivel no console — nunca perde em silencio.

### Envio proativo nas transicoes (console Fase B)

O write path das transicoes (`app/support/transitions.py`) passa a enfileirar,
na mesma transacao do evento:

- `-> in_progress`: notifica o cliente (free-form se janela aberta, senao
  template `atendente_assumiu`);
- `-> closed`: notifica + **resumo** (reusa `conversation_summaries` /
  `SummaryRecallService`, migration 012) via template `ticket_resolvido`;
- `waiting_customer` / `precisa_info`: template `precisa_info` se fora de janela.
- **e-mail em paralelo**: mesmo gatilho enfileira `email.message.requested`
  (`customers.email`), respeitando opt-out em `customer_preferences`.
- Idempotencia: `notify_customer:<case_id>:<to_status>` (um evento por transicao).

### Eventos de outbox

- `whatsapp.message.requested` (free-form; ja existe) — agora tambem para o
  cliente, com `phone` decifrado no momento do dispatch.
- `whatsapp.template.requested` (novo) — nome do template + parametros; o
  dispatcher chama o endpoint de template da Cloud API.
- `email.message.requested` (novo; transporte de e-mail no dispatcher: Juliano).

## Thin Bot Do Numero De Suporte

**Invariante:** o thin bot **nunca inicia** conversa — so **responde** a um
inbound do cliente. E o que garante que ele esta sempre dentro da janela de 24h
(nunca precisa de template) e nunca "cutuca" o cliente sozinho.

O unico automatismo no numero de suporte, e de proposito minimo:

- **ack de handoff / primeiro contato**: "Seu chamado #<codigo> de <data> foi
  passado para um atendente. Ele responde e resolve por aqui.";
- **horario comercial**: fora de `SUPPORT_BUSINESS_HOURS`, "Nosso time atende de
  X a Y; retornamos seu chamado assim que voltarmos.";
- **sem RAG, sem triagem**: correto porque o numero e handoff-only e o
  `context_snapshot_sanitized` + o transcript ja carregam o assunto. (Se um dia o
  numero for publicado, ai sim precisaria semear caso para inbound "a seco" — for
  a de escopo.)

Futuro possivel (nao-MVP): agent-assist (sugestao de resposta do RAG para o
atendente aprovar), sem responder o cliente automaticamente.

## Reuso Deliberado

- **Envio WhatsApp**: outbox + `whatsapp.message.requested` + dispatcher (Sprint
  5, ja envia WhatsApp para o time).
- **Console**: fila, detalhe com transcript, transicoes com CAS e eventos
  (Fases A/B do console) — o posto do atendente ja existe.
- **Resumo**: `conversation_summaries` + `SummaryRecallService` (migration 012).
- **E-mail**: `customers.email` (migration 013).
- **Identidade**: `verified_identities`/`CurrentIdentityResolver`, casamento por
  `phone_hash`.
- **Base Meta**: `app/integrations/meta_whatsapp/` (client/webhook/schemas), hoje
  por flag.

## Configuracao Nova

```text
ENABLE_WHATSAPP_SUPPORT_NUMBER=false      # liga a frente (dark por padrao)
META_SUPPORT_PHONE_NUMBER_ID=...          # numero de suporte na WABA
META_SUPPORT_WABA_ID=...
SUPPORT_WA_ENC_KEY=...                     # chave da cifra do wa_id (dedicada)
SUPPORT_WA_BINDING_MAX_DAYS=15             # teto de retencao do numero (purga)
SUPPORT_WA_WINDOW_HOURS=24                 # janela Meta (config p/ teste)
SUPPORT_BUSINESS_HOURS=Mon-Fri 09:00-18:00 # thin bot / auto-reply
SUPPORT_CONSOLE_TIMEZONE=America/Sao_Paulo # ja existe no console
SUPPORT_WA_TEMPLATES=atendente_assumiu,precisa_info,ticket_resolvido,reengajar
```

Flag off -> handler de inbound do numero de suporte e compositor ausentes
(`404`), nenhuma notificacao proativa enfileirada.

## Observabilidade

`log_event` sem PII, hashes truncados, **nunca** `wa_id`/telefone/transcript/
token/chave:

- `support_wa_inbound` (case_id, from/to janela, thin_bot_action)
- `support_wa_agent_message` (case_id, staff_id, delivery='freeform'|'template')
- `support_wa_notify_enqueued` (case_id, to_status, channel, template?)
- `support_wa_binding_purged` (case_id)

`wa_id` so aparece decifrado no dispatcher, nunca em log.

## Seguranca

- Frente dark por padrao; superficie ausente com a flag off.
- **Telefone cru cifrado, escopado ao caso, purgado no fechamento**; chave
  dedicada; decifra so no envio.
- Casamento de identidade por HMAC (nunca comparar telefone bruto).
- Compositor exige sessao staff + CSRF (`X-Requested-With`), como as escritas do
  console.
- Templates e janela respeitados no lado oficial (nao apoiar o produto no fato
  de o Hermes ignorar a janela).
- Numero de suporte handoff-only reduz superficie (sem inbound "a seco").
- Idempotencia em toda notificacao (`case_id + to_status`) e no envio.

## Prontidao E Dependencias Externas (Juliano / ops)

- **Provisionar o numero de suporte** na WABA (Meta), verificar, aquecer.
- **Aprovar os ~4 templates utility** (revisao da Meta leva tempo — dependencia
  de calendario).
- **Webhook Meta** apontando para o backend, roteando por phone number ID.
- **Transporte de e-mail** no dispatcher (para a notificacao paralela).
- **Runtime**: rodar Meta (numero suporte) ao lado do Hermes (numero bot) — nao
  ha conflito de sessao (numeros e caminhos distintos), mas e config de ambiente.
- Readiness alerta: `ENABLE_WHATSAPP_SUPPORT_NUMBER=true` exige
  `PERSISTENCE_BACKEND=postgres`, `SUPPORT_WA_ENC_KEY` presente, Meta configurado.

## Fases E Arquivos Provaveis

### Fase 0 - Pre-requisitos operacionais (Juliano)

Numero Meta provisionado, templates submetidos/aprovados, webhook configurado.
Sem codigo do nosso lado; destrava as fases seguintes.

### Fase 1 - Chat humano bidirecional in-window

Prova o loop inteiro dentro da janela de 24h, sem templates e sem push proativo.

- `migrations/016_case_whatsapp_bindings.sql` (+ `017` ator generico)
- cifra do `wa_id` (`app/support/wa_binding.py` novo: encrypt/decrypt + storage)
- roteamento de inbound do numero de suporte em
  `app/integrations/meta_whatsapp/webhook.py` -> handler novo (bind, append,
  thin bot ack/horario)
- compositor `POST /web/support/cases/{case_id}/message` em
  `app/api/routes/web_support.py` + schema
- deep link no handoff (numero bot -> numero suporte)
- `app/core/config.py`, `schema_contract.py`, readiness
- `tests/test_support_whatsapp_bridge.py` (bind por token, append, janela aberta
  envia free-form, thin bot, status de entrega, purga no fechamento e em 15 dias;
  sem PII em log)
- `runbooks/whatsapp-support-bridge-smoke.md` (a criar na entrega)

**Prova mais barata**: caso native-origin (numero ja conhecido) ou teste manual
com um numero controlado — nao depende de template nem de push.

### Fase 2 - Templates, reabertura de janela e notificacao proativa

Status: **implementada em codigo em 2026-07-05.** Achados relevantes durante a
implementacao: o resumo do fechamento usa
`support_cases.context_snapshot_sanitized.summary` (ja sincrono, mesma fonte
que `app/notifications/support_team.py` usa para o time) -- **nao**
`conversation_summaries`/`SummaryRecallService` como o plano original sugeria,
que e um sistema de resumo em lote (batch, chave por `domain+customer_ref`),
sem garantia de estar pronto no exato momento do fechamento. O opt-out de
e-mail (`app/support/customer_preferences.py`) foi o primeiro
leitor/escritor real de `customer_preferences` no projeto (nao existia
nenhum). "Precisa-info" e "reengajar" ficaram **staff-triggered** (o atendente
escolhe no compositor quando a janela esta fechada), enquanto
"atendente_assumiu"/"ticket_resolvido" ficaram **system-triggered** (na
transicao `claim`/`close`) -- so `claim` dispara `atendente_assumiu` (o
`resume` de `waiting_customer` tambem chega em `in_progress`, mas o cliente ja
sabe que ha um atendente, entao fica em silencio).

- `whatsapp.template.requested` no outbox + envio de template no dispatcher
- decisao free-form vs template no compositor e nas transicoes
- notificacoes proativas em `app/support/transitions.py` (assumiu/resolvido/
  precisa-info) + resumo no fechamento + e-mail paralelo com opt-out
- `email.message.requested` (transporte: Juliano; rota fica com transporte
  `disabled` de proposito ate o provedor ser decidido -- so enfileira)
- testes de janela (aberta/fechada), template fora de janela, idempotencia,
  opt-out de e-mail, resumo no closed

### Fase 3 - Unificacao de identidade (opcional, decisao aberta 2026-07-06)

Status: **pesquisa de codigo concluida em 2026-07-06; mecanismo NAO decidido
de proposito** -- pausado para o time se organizar antes de implementar.
Nenhum codigo escrito.

**Achado central (muda o enquadramento do problema):** "reconciliar os
dominios de hash" nao pode significar comparar os hashes ja gravados --
sao tres segredos diferentes, por construcao deliberada, e nenhum e
derivavel do outro:

| Hash | Formula | Segredo | Entrada |
| --- | --- | --- | --- |
| `verified_identities.phone_hash` (web) | `HMAC(secret, telefone)` direto | `IDENTITY_HASH_SECRET` | telefone E.164 |
| `conversations.session_hash` (WhatsApp nativo) | `HMAC(secret, "whatsapp:{hermes\|meta}:" + hash-interno(telefone))`, duas camadas | `PERSISTENCE_HASH_SECRET` | telefone pre-hasheado |
| `case_whatsapp_bindings.wa_id_hash` (ponte suporte) | `HMAC(secret+"\|hash", telefone)` | `SUPPORT_WA_ENC_KEY` | telefone E.164 |

Confirmado por leitura direta de `app/web_auth/service.py` (`_hmac_digest`),
`app/conversations/service.py` (`hash_session`) +
`app/integrations/hermes/chat_transport.py` /
`app/integrations/meta_whatsapp/chat_transport.py` (`_safe_*_session_id`), e
`app/support/wa_binding.py` (`hash_wa_id`). Nenhum join por igualdade entre
esses tres valores existe hoje nem e possivel sem recalcular um deles a
partir do telefone em claro.

**O que isso habilita:** o telefone em claro existe em tres pontos --
confirmacao de OTP web, inbound do WhatsApp nativo (Hermes/Meta, antes de
virar `session_hash`), e o binding da ponte de suporte (`wa_id_encrypted` e
decifravel). Em qualquer um desses pontos da para recalcular o hash do
**dominio web** (`HMAC(IDENTITY_HASH_SECRET, telefone)`) e resolver/criar
`customer_id` pela MESMA logica que `WebWhatsAppAuthStore.save_identity` ja
usa -- sem re-chavear nada, sem tocar nos hashes ja gravados.

**A decisao real nao e tecnica, e de fronteira de consentimento** (por isso
ficou aberta): quando aplicar esse recalculo?

- **Opcao A - todo inbound nativo (proativo):** toda mensagem no numero bot
  ja resolve/cria `customer_id` automaticamente. Mais unificacao, mas
  reverte silenciosamente a decisao de
  [customer-identity-whatsapp-handoff-plan.md](customer-identity-whatsapp-handoff-plan.md)
  de tratar o WhatsApp nativo como pseudonimo por padrao ("aceito como
  permanente, nao e gap a fechar") -- ninguem deu consentimento explicito
  para a correlacao entre canais.
- **Opcao B - so via OTP web (reativo, opt-in):** o historico so se une
  quando o cliente confirma OTP no site -- o backend recalcula o
  `session_hash` nativo esperado para aquele telefone e vincula
  retroativamente as conversas ja existentes. Quem nunca passa pelo web
  continua pseudonimo. Preserva a decisao anterior; e o mesmo gesto que ja
  existe hoje para o consent gate (Sprint 4b).

Nenhuma opcao foi escolhida ainda. Retomar esta secao antes de escrever
qualquer migration/codigo desta fase -- ela depende de uma decisao de
produto/privacidade, nao so de engenharia.

## Relacao Com O Painel De Status Web (decidido: opcao C)

Esta frente se sobrepoe ao
[web-chat-customer-ticket-status-plan.md](web-chat-customer-ticket-status-plan.md)
em "fechar o ciclo": la o cliente **puxa** status num painel web (re-OTP); aqui
ele **recebe** por WhatsApp. Se o cliente vive no WhatsApp, o painel web pull
perde razao de ser. Alternativas:

- **A - WhatsApp-only (matar o painel web):** close-the-loop 100% no WhatsApp +
  e-mail de fallback. Menos superficie, um lugar so pro cliente, sem atrito de
  re-OTP. Custo: quem nao usa WhatsApp depende do e-mail.
- **B - Painel web secundario:** WhatsApp e o principal; um "ver meus chamados"
  web magro cobre quem prefere web. Cobre mais gente, mas e codigo a manter com
  risco de virar orfao (a critica original ao pull).
- **C - Status dentro do widget web + CTA "continuar no WhatsApp":** nao um painel
  `/web/tickets` separado, e sim um bloco de status no widget que ja existe,
  empurrando pro WhatsApp. Minimo esforco, reaproveita o widget, usa a web como
  funil pro canal preferido. **(Recomendada.)**
- **D - Manter os dois em paralelo:** cobertura maxima, dobro de superficie pra
  ganho incremental baixo; contradiz "o valor migrou pro WhatsApp".

**Decisao (2026-07-04): opcao C.** O `web-chat-customer-ticket-status` Fase A
(painel `/web/tickets` separado, pull com re-OTP) fica **rebaixado — nao sera
construido como estava**: o status vira um **bloco dentro do widget web existente
+ CTA "continuar no WhatsApp"**. A `/web/tickets` como fachada propria sai do
roteiro. E-mail segue como canal paralelo para quem nao usa WhatsApp.

## Riscos Tecnicos

- **Telefone em repouso** (mesmo cifrado) amplia superficie: mitigado por escopo
  (so caso aberto), purga no fechamento **ou em 15 dias**, chave dedicada,
  decifra so no envio.
- **Baileys (numero bot) fragil/ban**: por isso o atendimento humano e o proativo
  ficam no numero **Meta**; o bot no Hermes e ponte temporaria.
- **Aprovacao de template** e dependencia externa de calendario: Fase 1 nao
  depende de template (fica in-window), entao nao bloqueia o inicio.
- **Corrida bot-vs-humano**: eliminada pelo modo-por-numero (suporte nao tem
  RAG).
- **Troca de numero para native-origin**: custo de UX aceito; mitigado por copy +
  clique unico; ganho e nao rodar atendimento no numero nao-oficial.
- **Duas threads no app do cliente**: tratado como organizacao (info no bot,
  chamado no suporte), nao como bug — decisao de produto.

## Validacao

```bash
python -m pytest
python -m compileall app tests scripts
python -m pytest tests/test_docs_links.py
```

- **Fase 1**: bind por token resolve o caso certo (token invalido -> erro
  amigavel, nunca caso errado); inbound anexa e reabre janela;
  compositor envia free-form dentro da janela e recusa (`409`) fora; thin bot
  responde ack/horario e nunca RAG; purga zera o `wa_id` no fechamento e no teto
  de 15 dias; caplog
  sem `wa_id`/telefone/token/chave; readiness acusa flag sem chave/persistencia/
  Meta.
- **Fase 2**: fora de janela envia template, nunca free-form; botao/inbound
  reabre; idempotencia por `case_id+to_status`; resumo no `closed`; e-mail
  respeita opt-out; sem e-mail salvo nao enfileira e-mail.
- Nao requer eval de dominio: nao toca prompt/retrieval/decisao de handoff no
  numero de suporte (ele nao tem RAG); o RAG do numero bot segue coberto pelos
  evals existentes.

## Dependencias E Sequencia

1. **Fase 0** (ops/Juliano): numero Meta + templates + webhook. Destrava tudo.
2. **Fase 1** depende das migrations 016/017 (Renan) e do numero Meta (Fase 0
   parcial: numero + webhook, sem templates ainda).
3. **Fase 2** depende dos templates aprovados (Fase 0) e do transporte de e-mail
   (Juliano).
4. **Fase 3** e opcional e independente do resto.
