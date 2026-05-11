# Observabilidade Minima

O MVP usa um padrao simples de rastreio por request para facilitar debug entre API, n8n, banco, retrieval e providers de LLM.

## Header de correlacao

Toda resposta HTTP deve retornar:

```http
X-Request-ID: trace-123
```

Regras:

- Se o cliente enviar `X-Request-ID`, a API reaproveita o valor.
- Se o cliente nao enviar, a API gera um UUID.
- Se o valor vier em branco ou maior que 80 caracteres, a API gera um novo UUID.
- O mesmo `request_id` aparece no corpo do `POST /chat`.
- Erros HTTP tratados e erros inesperados retornam `request_id` no corpo e no header.

## Como usar no n8n

Fluxo recomendado:

1. Gerar ou preservar um identificador por mensagem recebida.
2. Enviar esse valor no header `X-Request-ID`.
3. Guardar o `request_id` retornado pelo `/chat`.
4. Enviar esse `request_id` depois no `/feedback`.

## Logs estruturados

Os logs sao emitidos em JSON dentro da mensagem de log.

Eventos atuais:

- `http_request`: metodo, path, status e `request_id`.
- `http_error`: erro HTTP tratado com status e `request_id`.
- `validation_error`: erro de validacao com `request_id`.
- `unexpected_error`: erro inesperado com status 500, tipo do erro e `request_id`.
- `chat_completed`: dominio, `session_id_hash`, confianca, escalonamento, motivos e erro.
- `feedback_recorded`: feedback recebido, origem, `session_id_hash` e armazenamento atual.

## Campos importantes

- `request_id`: correlacao da chamada HTTP atual.
- `chat_request_id`: usado no feedback para apontar qual resposta do chat esta sendo avaliada.
- `domain`: dominio executado.
- `session_id_hash`: hash curto do identificador externo da conversa, quando existir.
- `error_code`: erro observavel, como `provider_error` ou `retrieval_error`.
- `handoff_reasons`: motivos de escalonamento para humano.

## Limite intencional do MVP

Esta frente nao adiciona APM, tracing distribuido, dashboards ou fila de logs. A ideia e criar um contrato simples agora para nao perder rastreabilidade quando as integracoes reais entrarem.
