# Contratos de Integracao

Este documento registra os contratos HTTP que outras frentes podem consumir, especialmente `n8n`, banco e futuros canais externos.

## Header `X-Request-ID`

Todas as chamadas podem enviar o header `X-Request-ID` para correlacionar logs e respostas.

Regras:

- Se enviado, o valor e reaproveitado quando tiver ate 80 caracteres.
- Se ausente, vazio ou grande demais, a API gera um novo UUID.
- Todas as respostas retornam `X-Request-ID`.
- Erros HTTP tratados tambem retornam `request_id` no corpo.
- O `request_id` do `/chat` deve ser preservado para envio posterior no `/feedback`.

## `POST /chat`

Entrada minima:

```json
{
  "domain": "suporte-vps-whatsapp",
  "session_id": "whatsapp:+5511999999999",
  "message": "Como conectar o WhatsApp na Evolution API?"
}
```

Validacoes:

- `message`: obrigatorio, sem branco puro, maximo 4000 caracteres.
- `session_id`: opcional, maximo 160 caracteres, branco vira `null`.
- `domain`: opcional, maximo 80 caracteres, branco vira `null`.

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
- A API retorna `references`; na persistencia PostgreSQL, este campo deve ser salvo em `messages.message_references`.

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

Validacoes:

- `helpful`: obrigatorio.
- `request_id`: opcional, maximo 80 caracteres, branco vira `null`.
- `session_id`: opcional, maximo 160 caracteres, branco vira `null`.
- `message_id`: opcional, maximo 80 caracteres, branco vira `null`.
- `reason`: opcional, maximo 120 caracteres, branco vira `null`.
- `comment`: opcional, maximo 1000 caracteres, branco vira `null`.
- `source`: obrigatorio por padrao como `api`, sem branco puro, maximo 60 caracteres.

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

## `POST /ingestion/preview`

Objetivo:

- Receber artigos, FAQs ou chamados curados em JSON.
- Normalizar conteudo.
- Gerar chunks para revisao antes da persistencia.
- Validar rapidamente se o material esta adequado para RAG.

Entrada minima:

```json
{
  "domain": "suporte-vps-whatsapp",
  "chunk_size": 800,
  "documents": [
    {
      "title": "Conexao WhatsApp",
      "source": "faq-qrcode.md",
      "content": "Texto do artigo ou FAQ..."
    }
  ]
}
```

Validacoes:

- `domain`: obrigatorio, sem branco puro, maximo 80 caracteres.
- `documents`: obrigatorio, minimo 1 e maximo 20 documentos.
- `documents[].title`: obrigatorio, sem branco puro, maximo 160 caracteres.
- `documents[].content`: obrigatorio, sem branco puro, maximo 20000 caracteres.
- `documents[].source`: opcional, maximo 240 caracteres, branco vira fonte automatica.
- `chunk_size`: opcional, minimo 200, maximo 2000, padrao 800.

Saida minima:

```json
{
  "request_id": "uuid-ou-header",
  "domain": "suporte-vps-whatsapp",
  "document_count": 1,
  "chunk_count": 2,
  "sample_chunks": ["primeiro chunk"],
  "chunks": [
    {
      "source": "faq-qrcode.md",
      "title": "Conexao WhatsApp",
      "text": "primeiro chunk",
      "chunk_index": 0
    }
  ]
}
```

Observacao:

- Este endpoint nao persiste dados.
- Este endpoint nao gera embeddings.
- O objetivo e revisar chunking e qualidade do conteudo antes de conectar banco, pgvector ou jobs de ingestao.

## `GET /ingestion/{domain_name}/preview`

Objetivo:

- Ler os arquivos locais ja existentes em `domains/<domain_name>/knowledge`.
- Retornar uma previa de documentos e chunks encontrados.

Uso esperado:

- Smoke test local do dominio.
- Conferencia rapida antes de rodar ingestao persistente no futuro.
