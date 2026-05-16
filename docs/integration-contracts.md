# Contratos de Integracao

Este documento registra os contratos HTTP que outras frentes podem consumir, especialmente `n8n`, banco e futuros canais externos.

Regra de modelagem:

- o banco e a API devem ser tratados como plataforma multi-dominio
- `suporte-vps-whatsapp` e apenas o primeiro dominio do projeto
- detalhes especificos de suporte, vendas, onboarding ou atendimento nao devem criar contratos HTTP separados sem necessidade real
- o isolamento logico entre setores continua vindo de `domain` no contrato e `domain_id` na persistencia

## Header `X-API-Key`

Rotas protegidas atualmente:

- `POST /chat`
- `POST /feedback`
- `POST /ingestion/preview`
- `POST /zoom/join`

Regra:

- o cliente deve enviar `X-API-Key` com a chave configurada em `API_SECRET_KEY`
- `API_SECRET_KEY` e obrigatoria fora de `APP_ENV=development`, `dev` ou `local`
- chamadas sem chave valida retornam `403`
- em staging, quando `ENABLE_CHAT_UI=true`, `POST /chat` tambem aceita `X-LLM-API-Key` para testes pela `/chat-ui`; esse atalho nao funciona em `APP_ENV=production`
- `GET /health`, `GET /domains`, `GET /ingestion/{domain_name}/preview` e `POST /zoom/webhook` continuam publicas no estado atual do MVP

Exemplo:

```http
X-API-Key: local-dev-api-key
```

O valor `local-dev-api-key` existe apenas como fallback local de desenvolvimento e nao deve ser usado em staging ou producao.

Exemplo de teste pela UI com chave do provider:

```http
X-LLM-API-Key: sk-...
```

Se `X-LLM-API-Key` for igual ao alias configurado em `PROJECT_LLM_API_KEY_ALIAS`, o backend usa a chave privada do ambiente, por exemplo `OPENAI_API_KEY`.
O valor real de `OPENAI_API_KEY` nunca deve ser enviado ao navegador, logado ou versionado.

Erro esperado sem chave valida:

```json
{
  "detail": "Invalid API key"
}
```

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
- campos extras sao rejeitados com `422`.
- o canal atual e texto-only; arquivos, anexos, uploads, imagens, PDFs ou metadados de arquivo nao fazem parte deste contrato.
- caracteres de controle no `message` sao removidos antes do fluxo de chat, sem alterar a defesa principal de seguranca do prompt e handoff.

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
- `n8n` deve enviar tambem `X-API-Key` quando consumir esta rota.
- a `/chat-ui` pode enviar `X-LLM-API-Key` em staging para permitir que cada pessoa teste com a propria chave do provider ou com o alias do projeto.
- Se `escalated=true`, `n8n` deve rotear para humano.
- `request_id` deve ser preservado em logs e feedback.
- A API retorna `references`; na persistencia PostgreSQL, este campo deve ser salvo em `messages.message_references`.

Contrato atual de `references`:

- hoje a API retorna uma lista de fontes rastreaveis do retrieval atual
- no estado atual do MVP, essas fontes costumam ser caminhos de arquivo em `domains/.../knowledge/...`
- quando a persistencia relacional estiver pronta, esse mesmo campo deve continuar sendo serializavel em JSON sem quebrar consumidores
- o contrato que outras frentes devem assumir hoje e `list[str]`
- se no futuro o backend passar a carregar metadados mais ricos de retrieval, isso deve entrar em um campo novo ou versao nova de contrato, sem quebrar `references`

Contrato atual de `handoff_reasons`:

- retorna motivos estruturados como `low_confidence`, `explicit_human_request`, `sensitive_topic`, `secret_request`, `prompt_injection_attempt` e `out_of_scope`
- integracoes externas nao devem inferir regra propria de negocio a partir do texto da resposta quando esse campo ja existir
- se `escalated=true`, o consumidor deve priorizar `handoff_reasons` para roteamento operacional

Contrato preparatorio para persistencia de resposta:

- `request_id`: identificador tecnico da resposta, obrigatorio para correlacao
- `domain`: dominio resolvido pelo backend, obrigatorio
- `answer`: texto final mostrado ao usuario
- `confidence`: numero serializavel para auditoria e calibragem
- `escalated`: booleano persistivel sem inferencia adicional
- `handoff_reasons`: lista serializavel de motivos estruturados
- `references`: lista serializavel de fontes recuperadas
- `error_code`: opcional, mas deve ser preservado quando existir

Fronteira de responsabilidade:

- este documento define o shape estavel que Renan pode travar por contrato
- a forma final de armazenamento em PostgreSQL, indices e tabelas continua na frente do Alexandre
- nenhuma integracao deve depender do retrieval lexical atual como implementacao permanente

## `POST /feedback`

Entrada minima:

```json
{
  "request_id": "uuid-retornado-pelo-chat",
  "session_id": "whatsapp:+5511999999999",
  "helpful": true,
  "reason": "resolved",
  "comment": "Resposta resolveu o caso",
  "source": "n8n",
  "escalated": true,
  "handoff_reasons": ["low_confidence"],
  "references": ["domains/suporte-vps-whatsapp/knowledge/faqs/qrcode-whatsapp.md"],
  "error_code": "provider_error"
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
- `escalated`: opcional.
- `handoff_reasons`: opcional, lista com ate 10 strings nao vazias.
- `references`: opcional, lista com ate 20 strings nao vazias.
- `error_code`: opcional, maximo 80 caracteres, branco vira `null`.

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
- esta rota tambem exige `X-API-Key`.

Contrato preparatorio para persistencia:

- `request_id` deve apontar para a resposta original do `/chat` quando existir
- `session_id` deve ser tratado como dado sensivel fora da API
- `message_id` continua opcional para permitir integracoes que ainda nao tenham ID interno de mensagem
- `helpful`, `reason`, `comment` e `source` devem continuar serializaveis sem conversao especial
- `escalated`, `handoff_reasons`, `references` e `error_code` podem ser reenviados
  pelo consumidor para preservar o contexto operacional da resposta avaliada
  sem exigir persistencia final imediata

Shape minimo recomendado para armazenamento futuro:

- `request_id`
- `session_id`
- `message_id`
- `helpful`
- `reason`
- `comment`
- `source`
- `accepted_at` ou timestamp equivalente definido pela frente de persistencia

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
- esta rota exige `X-API-Key` porque aceita payload livre e pode consumir recursos de processamento

Contrato preparatorio para retrieval e ingestao futura:

- `domain`, `source`, `title`, `text` e `chunk_index` devem continuar como campos basicos de interoperabilidade
- o backend atual nao promete IDs persistidos de chunk nesta rota
- quando a frente de banco ligar pgvector, IDs persistidos e metadados extras devem complementar esse payload sem quebrar os campos atuais

Fronteira de responsabilidade:

- Renan pode evoluir o contrato HTTP e os testes de contrato
- Alexandre implementa persistencia real de artigos, chunks, embeddings e consulta vetorial
- Juliano pode evoluir splitter e loaders sem quebrar o shape HTTP acordado aqui

## `GET /ingestion/{domain_name}/preview`

Objetivo:

- Ler os arquivos locais ja existentes em `domains/<domain_name>/knowledge`.
- Retornar uma previa de documentos e chunks encontrados.

Uso esperado:

- Smoke test local do dominio.
- Conferencia rapida antes de rodar ingestao persistente no futuro.
