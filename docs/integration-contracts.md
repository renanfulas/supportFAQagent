# Contratos de Integracao

Este documento registra os contratos HTTP que outras frentes podem consumir, especialmente `n8n`, banco e futuros canais externos.

## `POST /chat`

Entrada minima:

```json
{
  "domain": "suporte-vps-whatsapp",
  "session_id": "whatsapp:+5511999999999",
  "message": "Como conectar o WhatsApp na Evolution API?"
}
```

Saida minima:

```json
{
  "request_id": "uuid",
  "domain": "suporte-vps-whatsapp",
  "answer": "resposta ao usuario",
  "confidence": 0.82,
  "escalated": false,
  "handoff_reasons": [],
  "references": ["knowledge/faqs/qrcode-whatsapp.md"],
  "error_code": null
}
```

Uso esperado:

- `n8n` envia mensagens externas para este endpoint.
- Se `escalated=true`, `n8n` deve rotear para humano.
- `request_id` deve ser preservado em logs e feedback.

## `POST /feedback`

Entrada minima:

```json
{
  "request_id": "uuid-retornado-pelo-chat",
  "session_id": "whatsapp:+5511999999999",
  "helpful": true,
  "reason": "resolved",
  "comment": "Resposta resolveu o caso",
  "source": "n8n"
}
```

Saida atual:

```json
{
  "feedback_id": "uuid",
  "accepted": true,
  "status": "accepted",
  "storage": "pending_persistence"
}
```

Observacao:

- O contrato ja existe para desbloquear integracoes.
- A persistencia real entra quando a frente de banco estiver pronta.
- Enquanto isso, a resposta indica `pending_persistence`.

## Futuro `POST /ingest`

Objetivo:

- Receber artigos, FAQs ou chamados curados para ingestao.
- Normalizar conteudo.
- Gerar chunks.
- Enviar para o vector store oficial.

Status:

- Ainda nao implementado como contrato publico.
- Hoje existe apenas preview local por dominio em `GET /ingestion/{domain_name}/preview`.
