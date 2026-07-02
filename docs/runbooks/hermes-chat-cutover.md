# Runbook - Cutover do chat WhatsApp via Hermes (piloto)

Objetivo: fazer o bridge de WhatsApp do Hermes encaminhar o inbound para o nosso
backend (suporte/vendas) em vez do agente Hermes, de forma **gated por env e
reversivel**. Risco real: o bridge tambem serve o OTP do login; um restart derruba a
sessao por segundos.

Pre-requisitos ja feitos:

- Backup do `bridge.js` e da sessao em `/root/` (`bridge.js.bak-*`, `hermes-wa-session-*.tgz`).
- Nosso lado pronto e dormente (`ENABLE_HERMES_CHAT=false`).

## 1. Patch do bridge (gated; sem a env, comportamento identico)

Arquivo: `/usr/local/lib/hermes-agent/scripts/whatsapp-bridge/bridge.js`.

Garanta o import de crypto no topo (Baileys ja usa `randomBytes`):

```js
import crypto from 'crypto';
```

Config (junto dos outros `const ... = process.env...`):

```js
const CHAT_FORWARD_URL = process.env.HERMES_CHAT_FORWARD_URL || '';
const CHAT_FORWARD_SECRET = process.env.HERMES_CHAT_FORWARD_SECRET || '';
```

Helper (escopo de modulo):

```js
async function forwardToBackend(event) {
  try {
    const body = JSON.stringify(event);
    const ts = Math.floor(Date.now() / 1000).toString();
    const sig = crypto.createHmac('sha256', CHAT_FORWARD_SECRET).update(body).digest('hex');
    await fetch(CHAT_FORWARD_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Webhook-Timestamp': ts,
        'X-Webhook-Signature': sig,
      },
      body,
    });
  } catch (err) {
    console.error('[bridge] chat forward failed:', err.message);
  }
}
```

No `messages.upsert`, troque o enfileiramento:

```js
      // ANTES:
      // messageQueue.push(event);
      // if (messageQueue.length > MAX_QUEUE_SIZE) { messageQueue.shift(); }

      // DEPOIS:
      if (CHAT_FORWARD_URL) {
        forwardToBackend(event);            // -> nosso backend; NAO enfileira pro agente Hermes
      } else {
        messageQueue.push(event);
        if (messageQueue.length > MAX_QUEUE_SIZE) { messageQueue.shift(); }
      }
```

Requer Node 18+ (global `fetch`). Com `HERMES_CHAT_FORWARD_URL` vazio, o bridge se
comporta exatamente como hoje.

## 2. Subir nosso lado (supportfaqagent)

No `.env` de `/opt/supportFAQagent`:

```
ENABLE_HERMES_CHAT=true
HERMES_BRIDGE_URL=http://127.0.0.1:3000
ENABLE_WHATSAPP_DOMAIN_ROUTER=true   # para suporte E vendas no mesmo numero
```

`systemctl restart supportfaq.service` e confirmar `/health` 200.

## 3. Restart do bridge SEM forward (prova de saude)

Reinicie o `hermes-gateway.service` (ou o bridge) com `HERMES_CHAT_FORWARD_URL`
ainda vazio. Confirme: reconectou ao WhatsApp, `GET /health` do bridge ok, OTP de
login ainda entrega. Isso prova que o patch nao mudou nada.

## 4. Ligar o forward (cutover real)

Setar no ambiente do bridge:

```
HERMES_CHAT_FORWARD_URL=http://127.0.0.1:8000/integrations/hermes/chat/webhook
HERMES_CHAT_FORWARD_SECRET=<igual ao HERMES_WEBHOOK_SECRET>
```

Restart do bridge. A partir daqui o inbound (allowlist) vai pro nosso bot; o agente
Hermes para de responder nesse numero.

## 5. Smoke

Mandar uma mensagem de um numero da allowlist:

- "oi" -> deve vir a saudacao institucional (HostGator Brasil + assistente
  virtual); uma resposta ainda generica ("preciso de ajuda") -> pergunta de
  esclarecimento (suporte tecnico ou planos).
- "quero contratar um plano de hospedagem" -> resposta de vendas.
- "minha vps caiu" -> resposta de suporte.

## Rollback (imediato)

1. Remover `HERMES_CHAT_FORWARD_URL` do ambiente do bridge + restart -> volta pro
   agente Hermes na hora.
2. Se o `bridge.js` ficar ruim: `cp /root/bridge.js.bak-<ts>` por cima + restart.
3. Se a sessao quebrar: restaurar `hermes-wa-session-<ts>.tgz` em `/root/.hermes/`.
4. Desligar nosso lado: `ENABLE_HERMES_CHAT=false` + restart do supportfaq.

## Decisao de produto antes do passo 4

Ligar o forward = este numero deixa de ser o agente Hermes e vira o bot
suporte/vendas. Confirme a politica de allowlist e que a breve interrupcao de OTP no
restart e aceitavel. Alternativa mais segura: numero dedicado para o bot.
