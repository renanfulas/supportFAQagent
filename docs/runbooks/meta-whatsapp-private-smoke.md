# Runbook - Smoke Privado Meta WhatsApp E Hermes

## Objetivo

Validar a ativacao privada da fundacao Meta WhatsApp Cloud API e do adapter
temporario Hermes sem imprimir secrets, telefone bruto, OTP, payload completo
ou resposta de provider.

Este runbook nao substitui smoke real com numero de laboratorio. Ele cria o
gate operacional minimo para confirmar que:

- o webhook Meta responde a verificacao `hub.challenge`;
- a assinatura `X-Hub-Signature-256` e validada;
- o parser aceita payload de status sem disparar mensagem outbound;
- Hermes so e exercitado quando o operador pede explicitamente.

## Pre-requisitos

Antes do smoke real, rode o preflight sanitizado para confirmar se o ambiente
esta pronto sem imprimir valores privados:

```bash
python scripts/meta_whatsapp_activation_preflight.py --mode all
```

Modos disponiveis:

- `meta-webhook`: verifica configuracao minima para `hub.challenge` e
  assinatura Meta;
- `meta-chat`: verifica webhook, chat inbound e envio de resposta pela Meta;
- `meta-outbox-message`: verifica entrega de `whatsapp.message.requested` pelo
  dispatcher direto na Meta Cloud API;
- `meta-otp`: verifica entrega OTP nativa por template Meta;
- `hermes-otp`: verifica entrega OTP temporaria por Hermes.

O preflight mostra apenas nomes de variaveis presentes, ausentes ou invalidas.
Ele nao valida conectividade externa nem envia WhatsApp.

Para gerar uma evidencia versionavel depois do preflight e do smoke, salve os
relatorios sanitizados e consolide com:

```bash
python scripts/meta_whatsapp_activation_preflight.py \
  --mode all \
  --format json \
  --output /tmp/supportfaq-meta-preflight.json

python scripts/meta_whatsapp_activation_evidence.py \
  --environment private-lab \
  --operator Renan \
  --decision pending \
  --preflight-report /tmp/supportfaq-meta-preflight.json \
  --smoke-report /tmp/supportfaq-meta-smoke.md \
  --output /tmp/supportfaq-meta-activation-evidence.md
```

Use `--decision promote` somente depois que os checks do smoke estiverem verdes
e os logs privados tiverem sido revisados sem PII/secrets.

Opcionalmente, use o runner da suite para gerar preflight e evidencia em um
diretorio unico. Por padrao ele nao roda smoke nem envia WhatsApp:

```bash
python scripts/meta_whatsapp_activation_suite.py \
  --output-dir /tmp/supportfaq-meta-activation \
  --decision pending
```

Prefira um diretorio temporario fora do repositorio. Se usar a raiz do projeto
para diagnostico local, os nomes padrao `.tmp-meta*`, `supportfaq-meta-*`,
`supportfaq-hermes-*` e os relatorios `meta-whatsapp-*.json/md` ficam ignorados
pelo Git para reduzir risco de versionar evidencia operacional.

Para incluir smokes reais, adicione somente as flags desejadas, sempre com
numero de laboratorio. Exemplo:

```bash
python scripts/meta_whatsapp_activation_suite.py \
  --output-dir /tmp/supportfaq-meta-activation \
  --decision pending \
  --meta-webhook \
  --meta-chat-inbound \
  --meta-chat-from "+15551234567" \
  --meta-outbox-message \
  --meta-outbox-to "+15551234567" \
  --meta-otp \
  --meta-otp-phone "+15551234567"
```

Por padrao, `ready_for_promotion: true` exige todos estes checks no relatorio
consolidado:

Preflight:

- `meta-webhook`;
- `meta-chat`;
- `meta-outbox-message`;
- `meta-otp`.

Smoke:

- `meta_webhook_verification`;
- `meta_signed_status_webhook`;
- `meta_chat_inbound_message`;
- `meta_outbox_message_delivery`;
- `meta_otp_delivery`.

Checks parciais podem ser usados com `--decision pending` para diagnostico, mas
nao liberam promocao operacional. Hermes pode aparecer no preflight como
diagnostico/rollback temporario, mas nao e obrigatorio para promover a Meta
oficial.

Backend privado:

```dotenv
ENABLE_META_WHATSAPP_WEBHOOK=true
META_WHATSAPP_APP_SECRET=<private>
META_WHATSAPP_WEBHOOK_VERIFY_TOKEN=<private>
```

Para validar chat Meta em smoke posterior:

```dotenv
ENABLE_META_WHATSAPP_CHAT=true
META_WHATSAPP_ACCESS_TOKEN=<private>
META_WHATSAPP_PHONE_NUMBER_ID=<private>
META_WHATSAPP_GRAPH_API_VERSION=v25.0
```

Para validar entrega outbox de mensagem pela Meta:

```dotenv
OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT=meta_whatsapp
META_WHATSAPP_ACCESS_TOKEN=<private>
META_WHATSAPP_PHONE_NUMBER_ID=<private>
META_WHATSAPP_GRAPH_API_VERSION=v25.0
```

Para validar OTP por Meta em smoke posterior:

```dotenv
ENABLE_WEB_WHATSAPP_AUTH=true
WEB_AUTH_OTP_DELIVERY_TRANSPORT=meta
META_WHATSAPP_ACCESS_TOKEN=<private>
META_WHATSAPP_PHONE_NUMBER_ID=<private>
META_WHATSAPP_OTP_TEMPLATE_NAME=<approved-template>
```

Para validar Hermes temporario:

```dotenv
ENABLE_WEB_WHATSAPP_AUTH=true
WEB_AUTH_OTP_DELIVERY_TRANSPORT=hermes
HERMES_BASE_URL=<private>
HERMES_WEBHOOK_SECRET=<private>
HERMES_OTP_DELIVERY_PATH=/otp-delivery
```

## Smoke Meta Sem Envio Outbound

No ambiente privado:

```bash
export META_WHATSAPP_APP_SECRET="<private>"
export META_WHATSAPP_WEBHOOK_VERIFY_TOKEN="<private>"

python scripts/meta_whatsapp_private_smoke.py \
  --base-url http://127.0.0.1:8000 \
  --meta-webhook \
  --output /tmp/supportfaq-meta-smoke.md
```

Esse comando:

- chama `GET /integrations/meta/whatsapp/webhook`;
- envia um `POST` assinado com payload apenas de `statuses`;
- nao envia mensagem para WhatsApp;
- nao imprime token, app secret, payload bruto ou telefone.

## Smoke Meta Chat Inbound Com Resposta Controlada

Use apenas em laboratorio privado, porque se `ENABLE_META_WHATSAPP_CHAT=true`
este fluxo pode disparar uma resposta real pela Meta:

```bash
export META_WHATSAPP_APP_SECRET="<private>"

python scripts/meta_whatsapp_private_smoke.py \
  --base-url http://127.0.0.1:8000 \
  --meta-chat-inbound \
  --meta-chat-from "+15551234567" \
  --meta-chat-text "supportFAQagent private inbound smoke" \
  --output /tmp/supportfaq-meta-chat-inbound-smoke.md
```

Esse comando:

- envia um `POST /integrations/meta/whatsapp/webhook` assinado;
- usa payload `messages[].type="text"`;
- quando o backend estiver com `ENABLE_META_WHATSAPP_CHAT=true`, chama o fluxo
  interno de chat e tenta responder pela Meta;
- nao imprime telefone, texto inbound, token, payload bruto ou resposta bruta
  da Meta.

## Smoke Hermes Com Envio Controlado

Use apenas em laboratorio privado, porque este fluxo pode disparar uma entrega
real pelo servico Hermes configurado:

```bash
export HERMES_BASE_URL="<private>"
export HERMES_WEBHOOK_SECRET="<private>"

python scripts/meta_whatsapp_private_smoke.py \
  --hermes-otp \
  --hermes-phone "+15551234567" \
  --output /tmp/supportfaq-hermes-smoke.md
```

Use numero de laboratorio. Nao use telefone real de cliente. O argumento
`--hermes-phone` e obrigatorio; o smoke nao assume destinatario padrao para
fluxos que podem enviar mensagem real.

## Smoke Meta OTP Com Template Aprovado

Use apenas em laboratorio privado, porque este fluxo dispara um template real
pela Meta Cloud API:

```bash
export META_WHATSAPP_ACCESS_TOKEN="<private>"
export META_WHATSAPP_PHONE_NUMBER_ID="<private>"
export META_WHATSAPP_OTP_TEMPLATE_NAME="<approved-template>"
export META_WHATSAPP_OTP_TEMPLATE_LANGUAGE="pt_BR"

python scripts/meta_whatsapp_private_smoke.py \
  --meta-otp \
  --meta-otp-phone "+15551234567" \
  --meta-otp-code "000000" \
  --output /tmp/supportfaq-meta-otp-smoke.md
```

Esse comando:

- usa o `MetaWhatsAppOtpDeliveryAdapter`, o mesmo adapter do fluxo
  `/web/auth/whatsapp/start`;
- envia template OTP aprovado pela Meta;
- nao imprime telefone, OTP, token, payload bruto ou resposta bruta da Meta.

## Smoke Meta Outbox Com Envio Controlado

Use apenas em laboratorio privado, porque este fluxo dispara uma mensagem real
pela Meta Cloud API usando o dispatcher:

```bash
export OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT="meta_whatsapp"
export META_WHATSAPP_ACCESS_TOKEN="<private>"
export META_WHATSAPP_PHONE_NUMBER_ID="<private>"

python scripts/meta_whatsapp_private_smoke.py \
  --meta-outbox-message \
  --meta-outbox-to "+15551234567" \
  --meta-outbox-text "supportFAQagent private smoke" \
  --output /tmp/supportfaq-meta-outbox-smoke.md
```

Esse comando:

- chama o dispatcher com `event_type=whatsapp.message.requested`;
- exige payload minimo `to` e `text`;
- nao usa `OUTBOX_WEBHOOK_SECRET`, porque o transporte e Meta direto;
- nao imprime telefone, texto enviado, token ou resposta bruta da Meta.

## O Que O Relatorio Pode Conter

- data;
- nome do check;
- status HTTP;
- latencia;
- se o desafio foi ecoado;
- se o status foi aceito;
- se o inbound assinado foi aceito;
- se o envio outbound controlado foi aceito;
- se o template OTP Meta foi aceito;
- erro resumido como `http_error:<status>` ou `url_error:<tipo>`.
- nomes de variaveis ausentes ou invalidas no preflight;
- decisao operacional `pending`, `promote`, `rollback` ou `hold`.

## O Que Nao Pode Conter

- `META_WHATSAPP_APP_SECRET`;
- `META_WHATSAPP_WEBHOOK_VERIFY_TOKEN`;
- `META_WHATSAPP_ACCESS_TOKEN`;
- `HERMES_WEBHOOK_SECRET`;
- telefone real;
- OTP real;
- payload completo;
- headers completos;
- resposta bruta da Meta ou Hermes.

## Criterio De Pronto Do Smoke Privado

Meta webhook:

- `meta_webhook_verification` com `ok: true`;
- `meta_signed_status_webhook` com `ok: true`;
- logs do backend mostram apenas contagens, sem payload bruto.

Meta chat inbound:

- `meta_chat_inbound_message` com `ok: true`;
- resposta recebida no numero de laboratorio quando chat estiver habilitado;
- logs privados sem telefone bruto, texto inbound, token ou payload bruto.

Hermes:

- `hermes_otp_delivery` com `ok: true`;
- logs do Hermes sem telefone bruto, OTP ou secrets;
- o backend continua dono de OTP, expiracao, tentativas e validacao.

Meta OTP:

- `meta_otp_delivery` com `ok: true`;
- OTP recebido no numero de laboratorio usando template aprovado;
- logs privados sem telefone bruto, OTP, token ou resposta bruta da Meta.

Meta outbox message:

- `meta_outbox_message_delivery` com `ok: true`;
- mensagem recebida no numero de laboratorio;
- logs privados sem telefone bruto, texto enviado, token ou resposta bruta da
  Meta.

Evidencia de ativacao:

- modos Meta obrigatorios do preflight presentes e `ready: true`;
- relatorio de smoke consolidado com todos os checks Meta obrigatorios
  presentes e `ok: true`;
- `ready_for_promotion: true` somente quando a decisao for `promote`;
- revisao manual dos logs privados registrada fora do relatorio publico se
  houver qualquer dado operacional sensivel.

## Rollback

- `ENABLE_META_WHATSAPP_WEBHOOK=false` oculta a rota Meta com `404`;
- `ENABLE_META_WHATSAPP_CHAT=false` mantem parsing sem chamada ao core;
- `OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT=internal_webhook` volta a rota
  de mensagem WhatsApp para a fachada interna assinada;
- `WEB_AUTH_OTP_DELIVERY_TRANSPORT=memory` volta o OTP para laboratorio local;
- `WEB_AUTH_OTP_DELIVERY_TRANSPORT=meta` troca Hermes por Meta quando a
  ativacao oficial estiver pronta.
