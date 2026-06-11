# Runbook - Workflows n8n versionados

## Objetivo

Operacionalizar os templates versionados em `deploy/n8n/workflows/` sem
transformar o n8n em fonte de regras de negocio ou expor webhooks internos sem
autenticacao real.

Templates disponiveis:

- `whatsapp-to-bot.json`: recebe mensagem da Evolution API, chama `/chat` e
  envia a resposta pelo WhatsApp;
- `escalation-notify.json`: envia notificacao sanitizada de handoff ao grupo
  operacional;
- `web-otp-delivery.json`: transporta OTP criado pelo backend ate a Evolution
  API.

Todos os templates sao exportados com `active: false`, sem credenciais e sem
secrets.

## Fronteira obrigatoria de seguranca

Os webhooks internos de handoff e OTP somente podem ser ativados atras de um
ingress confiavel que valide:

- `X-Webhook-Timestamp` dentro da janela maxima de cinco minutos;
- `X-Webhook-Signature` HMAC-SHA256 sobre `timestamp + "." + raw_body`;
- `X-Idempotency-Key` ou `delivery_id` contra repeticao;
- tamanho e formato do payload.

O webhook de entrada da Evolution tambem deve ficar restrito a origem
confiavel por rede privada, allowlist ou mecanismo de autenticacao suportado
pela versao instalada. Nao publicar o endpoint sem essa barreira.

O nome `Verified ... Webhook` indica que essa validacao ocorreu antes do
workflow. O nome nao implementa a verificacao.

Nao apontar `HANDOFF_WEBHOOK_URL` ou `OTP_DELIVERY_WEBHOOK_URL` diretamente
para esses webhooks enquanto o ingress confiavel nao existir. Para validar o
dispatcher localmente, use:

```powershell
$env:OUTBOX_WEBHOOK_SECRET="<segredo-local>"
python -m scripts.mock_outbox_webhook --port 8765
```

O mock valida assinatura e janela temporal, mas guarda idempotencia somente em
memoria. Ele nao e componente de staging ou producao.

## Importacao segura

1. Importe os JSONs no n8n privado.
2. Crie credenciais `HTTP Header Auth` separadas para a API e para a Evolution.
3. Configure variables do n8n, sem valores no Git:

```text
SUPPORTFAQ_API_URL
EVOLUTION_API_BASE_URL
EVOLUTION_INSTANCE_NAME
HANDOFF_GROUP_ID
```

4. Confirme que `SUPPORTFAQ_API_URL` usa o nome interno do servico Docker.
5. Ajuste o mapeamento do payload da Evolution para a versao instalada.
6. Valide com dados anonimizados e workflow ainda inativo.
7. Ative apenas depois dos smokes e da verificacao do ingress.

## Smokes obrigatorios

- mensagem recebida chama `/chat` com `X-API-Key` por credencial privada;
- resposta da API e enviada ao mesmo identificador remoto;
- `request_id` e preservado;
- falha da API ou Evolution fica observavel e nao gera falso aceite;
- handoff e OTP sem assinatura valida sao rejeitados antes do n8n;
- retry com mesma chave nao cria segunda acao logica;
- execucoes e logs nao persistem telefone, OTP, mensagem bruta ou secrets.

## Limites atuais

- os templates assumem o shape comum da Evolution
  `body.data.key.remoteJid` e texto em `conversation` ou
  `extendedTextMessage.text`; confirmar o contrato da instancia real antes de
  ativar;
- o ingress HMAC persistente ainda precisa ser implementado no ambiente;
- nenhum template versionado equivale a smoke real com Evolution e WhatsApp.
