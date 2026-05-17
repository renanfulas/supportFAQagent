# Runbook - Contrato n8n/WhatsApp para `/chat`

## Objetivo

Definir como uma automacao externa, como n8n ou WhatsApp, deve consumir o
backend sem mover inteligencia, ranking, seguranca ou regras de dominio para o
workflow.

Este runbook prepara a integracao. Ele nao implementa workflow n8n, nao define
schema SQL e nao substitui a calibragem do `pgvector`.

## Chamada para `/chat`

Endpoint:

```http
POST /chat
```

Headers obrigatorios:

```http
Content-Type: application/json
X-API-Key: <api-secret-privado>
X-Request-ID: <id-estavel-da-mensagem-ou-conversa>
```

Payload minimo:

```json
{
  "domain": "suporte-vps-whatsapp",
  "session_id": "whatsapp:<identificador-sanitizado-ou-interno>",
  "message": "Mensagem do usuario"
}
```

Regras:

- `domain` deve ser enviado quando a automacao souber o dominio.
- `session_id` deve ser tratado como sensivel fora da API.
- `message` deve ser texto puro, sem anexos, arquivos, imagens ou metadados.
- O workflow nao deve enviar senhas, tokens, headers privados ou logs crus como
  parte da mensagem.

## Campos da resposta que o n8n deve preservar

Preservar em memoria operacional, log sanitizado ou persistencia futura:

- `request_id`
- `domain`
- `confidence`
- `escalated`
- `handoff_reasons`
- `references`
- `error_code`

O texto em `answer` e para o usuario final. Nao use o texto como unica fonte
para decidir roteamento quando `escalated` e `handoff_reasons` ja existem.

## Roteamento recomendado

- Se `error_code` nao for `null`, tratar como falha tecnica observavel.
- Se `escalated=true`, rotear para humano.
- Se `handoff_reasons` tiver `explicit_human_request`, priorizar atendimento.
- Se `handoff_reasons` tiver `sensitive_topic`, `secret_request` ou
  `prompt_injection_attempt`, nao tentar resolver no workflow.
- Se `confidence` estiver baixo mas `escalated=false`, registrar para revisao
  de qualidade.

## Feedback

Quando houver avaliacao humana ou resultado operacional, enviar:

```http
POST /feedback
```

Campos recomendados:

```json
{
  "request_id": "<request_id-do-chat>",
  "session_id": "<mesmo-session-id>",
  "helpful": true,
  "reason": "resolved",
  "source": "n8n",
  "escalated": false,
  "handoff_reasons": [],
  "references": ["domains/suporte-vps-whatsapp/knowledge/faqs/qrcode-whatsapp.md"],
  "error_code": null
}
```

## O que o workflow nao deve fazer

- nao decidir resposta com regra propria quando o backend ja respondeu
- nao reordenar `references`
- nao montar prompt ou contexto RAG
- nao ocultar `error_code`
- nao inferir handoff apenas pelo texto da resposta
- nao armazenar prompt completo, headers, payloads brutos, tokens ou PII
- nao publicar logs crus em documento, issue ou PR

## Smoke minimo de integracao

Antes de ligar canal real:

- `/health` responde `200`
- `/domains` lista o dominio esperado
- `/chat` responde `200` com `request_id`
- `X-Request-ID` enviado aparece no header e no corpo
- `references` e `handoff_reasons` sao arrays
- `error_code` e preservado
- se `escalated=true`, o workflow segue rota humana

## Observabilidade

No backend, o evento `chat_completed` deve ser suficiente para correlacionar:

- `request_id`
- `domain`
- `session_id_hash`
- `confidence`
- `escalated`
- `handoff_reasons`
- `error_code`
- `retrieval_backend`
- `references_count`

Nao registrar `session_id` bruto, mensagem original, resposta completa com PII,
secrets, payload bruto ou headers sensiveis.
