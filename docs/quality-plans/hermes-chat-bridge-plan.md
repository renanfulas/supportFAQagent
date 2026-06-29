# Plano Tecnico - Ponte de Chat Conversacional via Hermes (Piloto)

Status: **cutover concluido e verificado end-to-end na VPS (2026-06-29)**. O bridge
faz forward do inbound pro nosso webhook (`HERMES_CHAT_FORWARD_URL` setada,
`ENABLE_HERMES_CHAT=true`, allowlist `WHATSAPP_ALLOWED_USERS=*`). Teste real: "oi" ->
menu; "quero contratar um plano de hospedagem" -> resposta consultiva de vendas
(2x `hermes_chat_webhook_received` + HTTP 200; resposta entregue no WhatsApp).
Runbook em `docs/runbooks/hermes-chat-cutover.md`.
Pendencias conhecidas (nao bloqueiam o piloto): (1) a sessao Baileys do bridge pode
**travar** (loop `408/428` + `AwaitingInitialSync timeout`) e parar de processar
inbound sem matar o processo — remediado com `systemctl restart hermes-gateway.service`
(reconecta das credenciais, sem QR); (2) o canal Hermes ainda **nao emite
`chat_completed`**, entao falta observabilidade por turno no WhatsApp (so
`chat.py`/`web_chat.py` emitem).
Data de revisao: 2026-06-29.

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
- Stickiness em producao usa o store duravel `PgSessionDomainStore` (migration `011`):
  **`SESSION_DOMAIN_STORE_BACKEND=postgres` ja esta ligado na VPS** (verificado em
  2026-06-29). Ver `whatsapp-sticky-domain-routing-plan.md`.
- Meta WhatsApp Cloud API segue sendo o caminho estrategico; Hermes e ponte temporaria.
