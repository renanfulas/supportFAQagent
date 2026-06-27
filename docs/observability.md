# Observabilidade Minima

O MVP usa um padrao simples de rastreio por request para facilitar debug entre API, banco, retrieval, providers de LLM e integracoes externas como Meta WhatsApp ou Hermes.

## Header de correlacao

Toda resposta HTTP deve retornar:

```http
X-Request-ID: trace-123
```

Regras:

- Se o cliente enviar `X-Request-ID`, a API reaproveita o valor.
- Se o cliente nao enviar, a API gera um UUID.
- Se o valor vier em branco ou maior que 80 caracteres, a API gera um novo UUID.
- Se o valor contiver texto livre, caracteres fora do formato seguro ou
  prefixo reconhecivel de segredo, a API gera um novo UUID.
- O mesmo `request_id` aparece no corpo do `POST /chat`.
- Erros HTTP tratados e erros inesperados retornam `request_id` no corpo e no header.

## Como usar em consumidores externos

Fluxo recomendado:

1. Gerar ou preservar um identificador por mensagem recebida.
2. Enviar esse valor no header `X-Request-ID`.
3. Guardar o `request_id` retornado pelo `/chat`.
4. Enviar esse `request_id` depois no `/feedback`.

Para Meta WhatsApp, o webhook e o transporte devem preservar a correlacao sem
logar telefone bruto, corpo da mensagem, token, payload completo ou assinatura.
Para qualquer automacao externa, a regra continua a mesma: consumir contrato
HTTP e preservar `request_id`, sem carregar regra central do agente.

## Logs estruturados

Os logs sao emitidos em JSON dentro da mensagem de log.

Eventos atuais:

- `http_request`: metodo, path, status e `request_id`.
- `http_error`: erro HTTP tratado com status e `request_id`.
- `validation_error`: erro de validacao com `request_id`.
- `unexpected_error`: erro inesperado com status 500, tipo do erro e `request_id`.
- `chat_completed`: dominio, `session_id_hash`, confianca, escalonamento,
  motivos, erro, canal, `handoff_status`, `persistence_status`, reutilizacao de
  `request_id`, backend de retrieval, quantidade de referencias e tempos
  agregados do fluxo.
- quando houver falha do provider de LLM, `chat_completed` tambem pode registrar `provider_failure_kind` como metadado interno seguro, por exemplo `missing_credentials`, `provider_timeout`, `provider_request_error`, `empty_response` ou `initialization_error`.
- `chat_persistence_unavailable`: falha sanitizada ao gravar audit, conversa
  ou outbox, sem pergunta, resposta, sessao ou detalhe privado do banco.
- `conversation_history_unavailable`: historico indisponivel; o chat continua
  sem historico.
- `feedback_recorded`: feedback recebido, origem, `session_id_hash` e armazenamento atual.
- `webhook_ingress_rejected`: assinatura interna invalida, sem registrar payload.
- `webhook_ingress_delivery_failed`: encaminhamento ao destino verificado falhou.
- `webhook_ingress_delivered`: evento assinado entregue ao destino verificado.
- `meta_whatsapp_webhook_rejected`: assinatura Meta invalida, sem registrar payload.
- `meta_whatsapp_webhook_received`: webhook Meta aceito, registrando apenas contagem
  de mensagens e status.
- `outbox_dead_letter`: evento externo esgotou tentativas ou recebeu rejeicao definitiva.

Eventos e sinais importantes para a trilha de seguranca:

- `403` em rota protegida deve ser tratado como falha de autenticacao de integracao, nao como erro funcional do dominio
- `429` no `/chat` indica rate limiting e deve acionar retry com backoff no consumidor
- `handoff_reasons` e `escalated=true` devem ser preservados em logs ou automacoes externas sem depender do texto livre da resposta

## Campos importantes

- `request_id`: correlacao da chamada HTTP atual.
- `chat_request_id`: usado no feedback para apontar qual resposta do chat esta sendo avaliada.
- `domain`: dominio executado.
- `session_id_hash`: HMAC curto do identificador externo da conversa. Usa
  `PERSISTENCE_HASH_SECRET` quando configurado; sem ele, usa chave efemera por
  processo para evitar hash enumeravel, sem prometer correlacao entre restarts.
- `error_code`: erro observavel, como `provider_error` ou `retrieval_error`.
- `provider_failure_kind`: classificacao interna e segura da falha de provider, usada para diagnostico operacional sem mudar o contrato publico do `/chat`.
- `handoff_reasons`: motivos de escalonamento para humano.
- `retrieval_backend`: backend configurado no runtime, como `lexical` ou
  `pgvector`.
- `references_count`: quantidade de referencias retornadas, sem registrar o
  conteudo completo das fontes.
- `total_ms`: tempo total aproximado do fluxo de chat dentro da aplicacao.
- `retrieval_ms`: tempo aproximado gasto em retrieval.
- `llm_ms`: tempo aproximado gasto com inicializacao/chamada do provider LLM.
- `persistence_status`: confirma commit, persistencia desativada ou falha.
- `handoff_status`: diferencia decisao de escalar de handoff realmente
  enfileirado.
- `request_id_reused`: sinaliza reutilizacao do identificador para payload
  diferente.

## Health

- `GET /health` permanece liveness simples e retorna apenas `{"status":"ok"}`.
- `GET /health/ready` exige `X-API-Key` e separa banco, migrations, retrieval e
  outbox.
- banco, migration, pgvector indisponivel ou dominio ativo sem o minimo
  configurado de embeddings retornam `503`.
- dead letters ou backlog antigo deixam readiness `degraded`, mas nao derrubam
  a liveness nem produzem `503`.
- eventos `processing` sem lock ou acima de `OUTBOX_PROCESSING_STALE_SECONDS`
  tambem deixam a outbox `degraded`.
- tabelas essenciais ausentes para qualquer feature PostgreSQL habilitada
  deixam readiness indisponivel.
- o health detalhado nao chama LLM, embedding provider ou servico externo.
- thresholds de readiness podem ser ajustados por
  `HEALTH_PGVECTOR_MIN_DOMAIN_EMBEDDINGS`,
  `HEALTH_OUTBOX_READY_DEGRADED_COUNT` e
  `HEALTH_OUTBOX_OLDEST_READY_DEGRADED_SECONDS`; o dispatcher e o readiness
  compartilham `OUTBOX_PROCESSING_STALE_SECONDS`.

Campos que integracoes externas devem preservar:

- `request_id`
- `chat_request_id`
- `handoff_reasons`
- `error_code`
- `references`

## Dados proibidos em logs e relatorios

Mesmo em staging, nao registrar:

- prompt completo
- resposta completa quando houver risco de PII
- pergunta original com telefone, email, IP publico, dominio de cliente ou ID
  reversivel
- `DATABASE_URL`, API keys, tokens, senhas, cookies, headers sensiveis ou
  payload bruto
- hostname interno, usuario administrativo, porta administrativa ou stack trace
  com detalhe operacional sensivel

Quando for preciso compartilhar resultado com o time, preferir resumo
sanitizado com status HTTP, `request_id`, quantidade de `references`,
`confidence`, `escalated`, `handoff_reasons` e `error_code`.

## Limite intencional do MVP

Esta frente nao adiciona APM, tracing distribuido, dashboards ou fila de logs. A ideia e criar um contrato simples agora para nao perder rastreabilidade quando as integracoes reais entrarem.
