# Plano Tecnico - Ponte de Chat Conversacional via Hermes (Piloto)

Status: nosso lado do contrato implementado e dormente atras de `ENABLE_HERMES_CHAT`.
Ativacao depende do servico Hermes externo (frente Alexandre) e do runtime (Silotto).
Data de revisao: 2026-06-24.

## Objetivo

Validar rapido suporte E vendas conversando no WhatsApp via Hermes, reusando o mesmo
cerebro (`ChatFlowService`) e o `DomainRouter` com memoria pegajosa. E uma PONTE
TEMPORARIA: a via estrategica de chat continua sendo Meta WhatsApp Cloud API. Manter
o Hermes aqui apenas enquanto reduzir risco operacional, como diz o README.

## O que ja existe no nosso backend (este commit)

- Flag `ENABLE_HERMES_CHAT` (default false) + `HERMES_CHAT_DELIVERY_PATH`.
- `HermesClient.send_text(to, text, message_id)` — POST assinado para o
  `chat_delivery_path`, mesma assinatura HMAC do `deliver_otp`.
- Contrato e parser de inbound (`app/integrations/hermes/inbound.py`):
  `parse_hermes_inbound` + `verify_hermes_signature`.
- `HermesChatTransport` (espelho do Meta) reusando `ChatFlowService` + roteador +
  stickiness; sessao identificada por hash `whatsapp:hermes:<digest>` (nunca wa_id cru).
- Rota assinada `POST /integrations/hermes/chat/webhook`, 404 quando a flag esta off,
  401 com assinatura invalida, erros sanitizados.

## O contrato que o Hermes precisa cumprir (frente Alexandre)

PROPOSTO; confirmar e ajustar nomes de campo/caminho com o dono do Hermes.

### Inbound (Hermes -> nosso backend)

- Quando o Hermes receber uma mensagem do usuario, faz `POST` para
  `/integrations/hermes/chat/webhook` com:

  ```json
  { "messages": [ { "from": "<wa_id>", "id": "<message_id>", "type": "text", "text": "<body>" } ] }
  ```

- Headers de seguranca: `X-Webhook-Signature` = `HMAC_SHA256(HERMES_WEBHOOK_SECRET, body)`
  em hex, e `X-Webhook-Timestamp` (epoch). Janela de replay: 300s.

### Outbound (nosso backend -> Hermes)

- Recebemos a resposta do cerebro e fazemos `POST` assinado para
  `HERMES_BASE_URL + HERMES_CHAT_DELIVERY_PATH` com
  `{ "to", "text", "message_id" }`. O Hermes entrega ao destinatario no WhatsApp.
- Resposta opcional `{ "message_id": "<id do provedor>" }` (usada so para auditoria).

## Passos de ativacao (quando decidirem ligar o piloto)

1. Alexandre confirma/implementa no Hermes o forward de inbound e o endpoint de
   entrega de chat, com a mesma assinatura HMAC.
2. Silotto seta no `.env` da VPS: `ENABLE_HERMES_CHAT=true`, `HERMES_CHAT_DELIVERY_PATH`,
   e garante `HERMES_BASE_URL`/`HERMES_WEBHOOK_SECRET` (ja presentes para OTP).
3. Para suporte E vendas no mesmo numero, ligar tambem `ENABLE_WHATSAPP_DOMAIN_ROUTER=true`.
4. Apontar o webhook do Hermes para `/integrations/hermes/chat/webhook`.

## Riscos e limites honestos

- WhatsApp por caminho nao-oficial tem risco de bloqueio/banimento do numero (ver o
  artigo de risco no dominio de suporte). O Meta oficial existe para reduzir isso.
- Stickiness em producao precisa do store duravel (ver
  `whatsapp-sticky-domain-routing-plan.md`); o default em memoria nao sobrevive a
  restart nem e compartilhado entre workers.
- O formato de wire inbound/outbound aqui e PROPOSTO; so vai para producao depois de
  casar com o que o Hermes realmente fala.
- Toda a inteligencia (resposta, handoff, confinamento) permanece no backend; o
  Hermes e so transporte.
