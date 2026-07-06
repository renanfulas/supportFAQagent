# Runbook - Smoke da ponte WhatsApp<->console (Fase 1)

Roteiro de validacao do numero de suporte e do compositor do console em
staging antes de promover a producao. Plano tecnico:
[whatsapp-support-bridge-tech-plan.md](../quality-plans/whatsapp-support-bridge-tech-plan.md).
Depende de pre-requisitos externos (Juliano) que este runbook nao cobre:
provisionamento do numero de suporte na Meta e o webhook apontando pro
backend.

## Pre-requisitos

1. Migrations `016_case_whatsapp_bindings.sql`, `017_support_case_events_actor_kind.sql`
   e `018_messages_delivery_status.sql` aplicadas
   (`python scripts/migrate.py`).
2. `PERSISTENCE_BACKEND=postgres` ativo.
3. Numero de suporte provisionado na WABA (Juliano): `META_SUPPORT_PHONE_NUMBER_ID`
   (para as chamadas da Cloud API) e `META_SUPPORT_PHONE_NUMBER_E164` (numero
   discavel, so para o deep link `wa.me`) configurados; webhook Meta apontando
   pro backend, roteando por `phone_number_id`.
4. Chaves dedicadas geradas e configuradas: `SUPPORT_WA_ENC_KEY` (cifra do
   `wa_id`) e `SUPPORT_WA_TOKEN_SECRET` (assinatura do token do deep link) --
   **nunca** reusar `IDENTITY_HASH_SECRET`.
5. `ENABLE_WHATSAPP_SUPPORT_NUMBER=true` no ambiente e servico reiniciado.
6. `GET /health/ready` com o componente `whatsapp_bridge` em `ok` (ele acusa
   persistencia ausente, numero/chaves faltando ou tabela `case_whatsapp_bindings`
   ausente).
7. Um caso de teste com escalacao real (ex.: WhatsApp nativo perguntando algo
   fora de escopo, ou web chat com handoff) para gerar o deep link.

## Smoke pela API

Guardar os `request_id`/`case_id` das respostas.

1. **Dark por padrao** (antes de ligar a flag): `POST /web/support/cases/{id}/message`
   responde `404`.
2. **Deep link no handoff**: escalar um caso real (native ou web) e conferir
   `support_deep_link` na resposta (`WebChatResponse`/`HandoffConsentResponse`)
   ou, no WhatsApp nativo, o link `https://wa.me/<numero>?text=...` anexado ao
   texto da resposta do bot.
3. **Primeiro contato no numero de suporte**: tocar o deep link e mandar a
   mensagem pre-preenchida (com o token). Esperado: mensagem de ack ("seu
   chamado foi passado para um atendente..."); `GET /web/support/cases/{case_id}`
   (console) mostra a mensagem do cliente no transcript (`role=user`,
   `channel=whatsapp_support`).
4. **Token invalido/sem vinculo**: mandar mensagem "a seco" pro numero de
   suporte de um numero sem binding e sem token → resposta generica ("nao
   encontrei um atendimento..."); nada e criado no banco.
5. **Caso fechado nao reabre**: usar o deep link de um caso ja `closed` →
   mesma resposta generica de nao encontrado.
6. **Compositor dentro da janela**: no console, `POST /web/support/cases/{case_id}/message`
   com `{"message": "..."}` e `X-Requested-With: XMLHttpRequest` → `200
   {message_id, status: queued}`; a mensagem chega no WhatsApp do cliente;
   `GET /web/support/cases/{case_id}` mostra a resposta no transcript
   (`role=agent`) e o evento correspondente.
7. **CSRF**: mesmo POST sem `X-Requested-With` → `403 csrf_header_required`.
8. **Sem binding**: compositor num caso sem cliente vinculado ainda →
   `409 {code: no_whatsapp_binding}`.
9. **Janela fechada**: aguardar (ou simular) mais de 24h sem mensagem do
   cliente e tentar responder → `409 {code: window_closed, templates:
   ["precisa_info", "reengajar"]}` (lista real, Fase 2).
10. **Repeat contact**: cliente ja vinculado manda nova mensagem dentro do
    horario comercial → sem ack automatico (silencio do thin bot); fora do
    horario configurado (`SUPPORT_BUSINESS_HOURS_*`) → ack com aviso de
    horario.
11. **Status de entrega**: apos o compositor enviar, conferir nos logs/no
    banco que `messages.delivery_status` evolui de `sent` para `delivered`
    (ou `read`) conforme o webhook de status da Meta chega; nenhuma callback
    tardia deve regredir o status.
12. **Logs**: conferir `support_wa_inbound`, `support_wa_agent_message`,
    `support_wa_inbound_unmatched` sem `wa_id`, telefone bruto, token ou
    conteudo da mensagem em claro alem do necessario.

## Smoke da Fase 2 (templates, notificacao proativa, e-mail)

Requer os 4 templates (`atendente_assumiu`, `precisa_info`,
`ticket_resolvido`, `reengajar`) aprovados na WABA e os
`SUPPORT_WA_TEMPLATE_*` configurados com os nomes reais aprovados.

1. **Retry via template**: com a janela fechada (item 9 acima), reenviar com
   `{"message": "...", "template": "precisa_info"}` → `200` com `delivery:
   "template"`; a mensagem chega como template aprovado (nao free-form).
2. **Template invalido**: `{"message": "...", "template": "qualquer_coisa"}`
   → `422 {code: unknown_template, templates: [...]}`.
3. **Claim notifica o cliente**: assumir um caso (`claim`) com binding WA
   ativo e janela aberta → o cliente recebe free-form ("um atendente assumiu
   seu chamado..."); com a janela fechada → template `atendente_assumiu`.
4. **Close notifica com resumo**: fechar (`close`) um caso com binding ativo
   → o cliente recebe o resumo do caso (via free-form ou `ticket_resolvido`
   conforme a janela).
5. **Resume fica em silencio**: `waiting_customer -> resume` (via `resume`)
   nao gera nenhuma notificacao ao cliente (so `claim` dispara
   `atendente_assumiu`).
6. **E-mail paralelo**: com `customers.email` preenchido e sem opt-out, o
   evento `email.message.requested` e enfileirado (visivel no
   `operational_outbox`); com `OUTBOX_EMAIL_DELIVERY_TRANSPORT` ainda no
   default (`disabled`), o dispatcher marca o evento `dead_letter` de
   proposito (nenhum transporte real existe ainda) -- **isto e esperado**
   ate o provedor ser decidido.
7. **Opt-out de e-mail**: com `customer_preferences.preferences_json =
   {"notify_status_by_email": false}` para o cliente, nenhum
   `email.message.requested` e enfileirado na transicao.
8. **Idempotencia**: repetir a mesma transicao (ex.: retry de rede) nao
   duplica o evento de notificacao (`notify_customer_wa:<case>:<status>` /
   `notify_customer_email:<case>:<status>`).

## Retencao do wa_id (verificar em staging, nao apressar em produção)

- Fechar um caso com binding ativo e confirmar que `case_whatsapp_bindings.wa_id_encrypted`
  foi zerado (`unbound_at` preenchido).
- Validar (pode ser com `now` adiantado em teste, nao esperar 15 dias de
  verdade) que o job/rotina de purga (`purge_expired`) zera bindings vencidos
  por `SUPPORT_WA_BINDING_MAX_DAYS`.

## Promocao a producao

Repetir a sequencia inteira em producao (migrations → numero/chaves → flag →
smoke API). Rollback: `ENABLE_WHATSAPP_SUPPORT_NUMBER=false` devolve `404` na
superficie do compositor e para o roteamento por numero de suporte, sem tocar
dados; o numero bot e o console (`/web/support/*`) continuam intocados.

## Incidentes conhecidos

- **Meta rejeita free-form dentro da janela aparente**: a janela e
  autoritativa do lado da Meta, `last_customer_message_at` e so espelho —
  tratar como residual (Fase 2 cobre o fallback pra template).
- **Rotacao de `SUPPORT_WA_ENC_KEY`**: invalida a decifra de todo binding
  vivo (o `wa_id` fica ilegivel). Nao ha procedimento de "recadastro" como no
  staff — os casos afetados precisam de um novo vinculo (novo deep link).
