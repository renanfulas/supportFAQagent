# Runbook - Smoke privado da notificacao WhatsApp para o time (Sprint 5)

Objetivo: validar, em ambiente privado, que um handoff gera um alerta WhatsApp
para os destinatarios internos, sem vazar PII e sem derrubar o ticket.

Esta frente e dark por padrao. Em producao normal nenhum evento de notificacao e
enfileirado ate as flags abaixo serem ligadas deliberadamente.

## Pre-condicoes

- `PERSISTENCE_BACKEND=postgres` ativo (handoff precisa gravar `support_cases`).
- Dispatcher da outbox rodando (`scripts/dispatch_outbox.py --loop`).
- Para envio real: transporte Meta configurado e validado pelo smoke privado do
  Meta WhatsApp (ver `docs/runbooks/meta-whatsapp-private-smoke.md`).

## Modos de operacao

### 1. Auditavel sem enviar (recomendado para o primeiro smoke)

```dotenv
ENABLE_SUPPORT_TEAM_WHATSAPP_NOTIFY=true
SUPPORT_TEAM_WHATSAPP_RECIPIENTS=5511999990001,5511999990002
OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT=disabled
```

- Um handoff passa a enfileirar um `whatsapp.message.requested` por destinatario.
- Com o transporte `disabled`, o dispatcher nao envia; os eventos ficam
  auditaveis em `operational_outbox` (e viram dead_letter, sem sair da box).
- Confirme em `operational_outbox` que ha um evento por destinatario com
  `to`/`text` esperados e `idempotency_key = support_notify:<turn_id>:<hash>`.

### 2. Envio real em ambiente privado

```dotenv
ENABLE_SUPPORT_TEAM_WHATSAPP_NOTIFY=true
SUPPORT_TEAM_WHATSAPP_RECIPIENTS=<numeros internos autorizados>
OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT=meta_whatsapp
# + secrets Meta (META_WHATSAPP_ACCESS_TOKEN, META_WHATSAPP_PHONE_NUMBER_ID, ...)
```

- Dispare um turno que escale para humano e confirme que cada destinatario recebe
  o alerta curto (caso, dominio, motivo, resumo, referencias).

## Checks obrigatorios

- [ ] Um handoff gera N eventos `whatsapp.message.requested` (N = destinatarios).
- [ ] Retry do mesmo turno nao cria evento duplicado por destinatario.
- [ ] Com `ENABLE_SUPPORT_TEAM_WHATSAPP_NOTIFY=false`, nenhum evento e enfileirado.
- [ ] O `support_case` e o `handoff.requested` existem mesmo se o envio falhar.
- [ ] Logs nao contem telefone bruto do cliente, OTP, token ou payload completo.
- [ ] O `to` do destinatario interno chega verbatim ao dispatcher (nao redatado).

## Rollback

- Definir `ENABLE_SUPPORT_TEAM_WHATSAPP_NOTIFY=false` desliga o fan-out na origem.
- Definir `OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT=disabled` para de enviar
  mantendo a auditabilidade dos eventos ja enfileirados.
