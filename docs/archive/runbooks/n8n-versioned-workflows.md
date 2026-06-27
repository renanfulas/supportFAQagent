# Runbook - Workflows n8n versionados

Status: ARQUIVADO. `n8n` foi removido do projeto; os templates em
`deploy/n8n/workflows/` e os aliases `N8N_VERIFIED_*_URL` citados abaixo nao
existem mais no repo nem na config. Use este runbook apenas para auditar
workflows historicos. A direcao atual de WhatsApp esta em
`../../quality-plans/meta-whatsapp-native-integration-plan.md` e
`../../runbooks/meta-whatsapp-private-smoke.md`.

## Objetivo

Operacionalizar os templates versionados em `deploy/n8n/workflows/` sem
transformar o n8n em fonte de regras de negocio ou expor webhooks internos sem
autenticacao real.

Templates disponiveis:

- `whatsapp-to-bot.json`: recebe mensagem da Evolution API, chama `/chat` e
  envia a resposta pelo WhatsApp, sem duplicar notificacao de handoff;
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

O webhook de entrada da Evolution usa `headerAuth` no template e tambem deve
ficar restrito a origem confiavel por rede privada ou allowlist. A credencial
nao e versionada e precisa ser associada no n8n antes da ativacao. Nao
publicar o endpoint sem essas barreiras.

O nome `Verified ... Webhook` indica que essa validacao ocorreu antes do
workflow. O nome nao implementa a verificacao.

O ingress confiavel agora existe na API e permanece opt-in. Configure o
dispatcher para chamar:

```text
HANDOFF_WEBHOOK_URL=http://supportfaq_api:8000/internal/webhooks/outbox/handoff.requested
WHATSAPP_MESSAGE_WEBHOOK_URL=http://supportfaq_api:8000/internal/webhooks/outbox/whatsapp.message.requested
OTP_DELIVERY_WEBHOOK_URL=http://supportfaq_api:8000/internal/webhooks/outbox/otp.delivery.requested
```

Na API, configure os destinos finais privados:

```text
ENABLE_OUTBOX_INGRESS=true
N8N_VERIFIED_HANDOFF_URL=<webhook-interno-n8n>
N8N_VERIFIED_WHATSAPP_URL=<webhook-interno-n8n>
N8N_VERIFIED_OTP_URL=<webhook-interno-n8n>
```

Para validar o dispatcher isoladamente, use:

```powershell
$env:OUTBOX_WEBHOOK_SECRET="<segredo-local>"
python -m scripts.mock_outbox_webhook --port 8765
```

O mock valida assinatura e janela temporal, mas guarda idempotencia somente em
memoria. Ele nao e componente de staging ou producao.

Para validar o contrato de saida da Evolution sem WhatsApp real:

```powershell
$env:EVOLUTION_API_KEY="<segredo-local>"
python -m scripts.mock_evolution_api --port 8770
```

O mock valida `apikey`, rota `message/sendText/<instancia>` e payload
`number/text`. `EVOLUTION_MOCK_FORCE_STATUS=429` ou `500` simula falha.

## Importacao segura

1. Importe os JSONs no n8n privado.
2. Crie credenciais `HTTP Header Auth` separadas para a API e para a Evolution.
3. Associe uma credencial `HTTP Header Auth` ao `Authenticated Evolution Webhook`.
4. Configure variables do n8n, sem valores no Git:

```text
SUPPORTFAQ_API_URL
EVOLUTION_API_BASE_URL
EVOLUTION_INSTANCE_NAME
HANDOFF_GROUP_ID
```

5. Confirme que `SUPPORTFAQ_API_URL` usa o nome interno do servico Docker.
6. Ajuste o mapeamento do payload da Evolution para a versao instalada.
7. Valide com dados anonimizados e workflow ainda inativo.
8. Ative apenas depois dos smokes e da verificacao do ingress.

## Smokes obrigatorios

- mensagem recebida chama `/chat` com `X-API-Key` por credencial privada;
- resposta da API e enviada ao mesmo identificador remoto;
- `request_id` e preservado;
- falha da API ou Evolution fica observavel e nao gera falso aceite;
- handoff e OTP sem assinatura valida sao rejeitados antes do n8n;
- retry com mesma chave nao cria segunda acao logica;
- a chave `X-Idempotency-Key` recebida e propagada ate a chamada da Evolution;
  o provider ou proxy final precisa honrar essa chave para eliminar a janela
  residual de duplicacao apos timeout incerto;
- `whatsapp-to-bot` nao envia notificacao humana paralela quando a API ja
  retornou `handoff_status=handoff_queued`;
- execucoes e logs nao persistem telefone, OTP, mensagem bruta ou secrets.
- `EXECUTIONS_DATA_SAVE_ON_SUCCESS=none` e
  `EXECUTIONS_DATA_SAVE_ON_ERROR=none` permanecem ativos enquanto os workflows
  recebem payload bruto de canais externos.

## Limites atuais

- os templates assumem o shape comum da Evolution
  `body.data.key.remoteJid` e texto em `conversation` ou
  `extendedTextMessage.text`; confirmar o contrato da instancia real antes de
  ativar;
- o ingress HMAC persistente e a migration `005` estao implementados; o
  ambiente precisa ter migrations `001-008` verificadas e o ingress validado
  por smoke privado;
- nenhum template versionado equivale a smoke real com Evolution e WhatsApp.
- sem suporte de idempotencia na Evolution ou no proxy final, entrega continua
  at-least-once e um timeout depois do side effect ainda exige reconciliacao
  operacional; nao declarar exactly-once.
