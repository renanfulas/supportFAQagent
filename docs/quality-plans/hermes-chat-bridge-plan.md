# Plano Tecnico - Ponte de Chat Conversacional via Hermes (Piloto)

Status: nosso lado pronto e dormente atras de `ENABLE_HERMES_CHAT`. Falta o cutover
no bridge (patch gated por env) + a decisao de produto. Runbook em
`docs/runbooks/hermes-chat-cutover.md`.
Data de revisao: 2026-06-24.

## Arquitetura real (investigada na VPS)

- O WhatsApp roda num bridge node bespoke (`/usr/local/lib/hermes-agent/scripts/
  whatsapp-bridge/bridge.js`, Baileys, express :3000, `--mode bot`, allowlist
  `WHATSAPP_ALLOWED_USERS`). Segura UMA sessao de WhatsApp.
- Inbound: `messages.upsert` monta um `event` e faz `messageQueue.push(event)`.
- `GET /messages` DRENA a fila (`splice`) — consumidor unico. Hoje o gateway Hermes
  (`hermes_cli` :8644) faz polling e responde como agente.
- Outbound: `POST /send {chatId, message}` (localhost, sem HMAC).
- O OTP do login sai pelo mesmo gateway/bridge. Quebrar o bridge quebra o login.

## Nosso lado (implementado, dormente)

- `HermesBridgeClient.send_text` -> `POST {HERMES_BRIDGE_URL}/send {chatId, message}`.
- `parse_hermes_inbound` aceita o `event` nativo do bridge (`chatId`, `senderId`,
  `body`, `messageId`, `isGroup`); ignora grupo e vazio.
- `verify_hermes_signature`: `HMAC_SHA256(HERMES_WEBHOOK_SECRET, body)` em hex +
  `X-Webhook-Timestamp` (replay 300s).
- `HermesChatTransport`: inbound -> `ChatFlowService` + roteador + stickiness ->
  resposta pelo bridge `/send`. Sessao por hash `whatsapp:hermes:<digest>`.
- Rota `POST /integrations/hermes/chat/webhook` (404 com flag off, 401 sem assinatura).
- Flags: `ENABLE_HERMES_CHAT` (off), `HERMES_BRIDGE_URL` (default `http://127.0.0.1:3000`).

## O cutover (patch gated, reversivel)

O bridge passa a dar forward do inbound pro nosso webhook E para de enfileirar pro
agente Hermes (sem double-bot) — mas APENAS quando `HERMES_CHAT_FORWARD_URL` esta
setada. Sem a var, comportamento identico ao de hoje. Ver o patch e os passos em
`docs/runbooks/hermes-chat-cutover.md`.

## Decisao de produto (gate humano)

Ativar o forward significa: **este numero deixa de ser o agente Hermes e passa a ser
o bot de suporte/vendas do supportFAQagent**, para quem estiver na allowlist. Quem
decide a politica da allowlist e se a breve interrupcao de OTP (janela de restart do
bridge) e aceitavel e o dono do produto. Recomendacao mais segura: usar um NUMERO
DEDICADO para o bot, deixando o numero de OTP/agente intacto.

## Riscos

- Caminho nao-oficial de WhatsApp tem risco de bloqueio/banimento do numero.
- Restart do bridge derruba a sessao por segundos (afeta OTP nesse intervalo);
  reconecta das credenciais (backup feito).
- Stickiness em producao precisa do store duravel (ver
  `whatsapp-sticky-domain-routing-plan.md`).
- Meta WhatsApp Cloud API segue sendo o caminho estrategico; Hermes e ponte temporaria.
