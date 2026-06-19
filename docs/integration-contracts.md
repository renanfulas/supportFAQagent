# Contratos de Integracao

Este documento registra os contratos HTTP que outras frentes podem consumir,
especialmente Meta WhatsApp, Hermes temporario, banco, consumidores legados e
futuros canais externos.

Regra de modelagem:

- o banco e a API devem ser tratados como plataforma multi-dominio
- `suporte-vps-whatsapp` e apenas o primeiro dominio do projeto
- detalhes especificos de suporte, vendas, onboarding ou atendimento nao devem criar contratos HTTP separados sem necessidade real
- o isolamento logico entre setores continua vindo de `domain` no contrato e `domain_id` na persistencia

## Header `X-API-Key`

Rotas protegidas atualmente:

- `GET /health/ready`
- `GET /domains`
- `POST /chat`
- `POST /feedback`
- `POST /ingestion/preview`
- `GET /ingestion/{domain_name}/preview`
- `POST /zoom/join`
- `POST /zoom/webhook`

Rotas publicas controladas atualmente:

- `POST /web/chat`
- `POST /web/feedback`
- `POST /web/auth/whatsapp/start` quando `ENABLE_WEB_WHATSAPP_AUTH=true`
- `POST /web/auth/whatsapp/confirm` quando `ENABLE_WEB_WHATSAPP_AUTH=true`
- `GET /web/auth/session` quando `ENABLE_WEB_WHATSAPP_AUTH=true`
- `POST /web/auth/logout` quando `ENABLE_WEB_WHATSAPP_AUTH=true`

Regra:

- o cliente deve enviar `X-API-Key` com a chave configurada em `API_SECRET_KEY`
- `API_SECRET_KEY` e obrigatoria fora de `APP_ENV=development`, `dev` ou `local`
- chamadas sem chave valida retornam `403`
- em staging, quando `ENABLE_CHAT_UI=true`, `POST /chat` tambem aceita `X-LLM-API-Key` para testes pela `/chat-ui`; esse atalho nao funciona em `APP_ENV=production`
- `GET /health` continua publica no estado atual do MVP
- `GET /health/ready` exige `X-API-Key` porque inclui diagnosticos operacionais
- `POST /zoom/webhook` tambem aceita segredo compartilhado via query string quando `ZOOM_WEBHOOK_SECRET` estiver configurado para integracoes controladas com Recall/Zoom
- `POST /web/chat` e `POST /web/feedback` nao aceitam nem exigem `X-API-Key` no navegador; essa superficie publica controlada usa sessao anonima por cookie e continua chamando o mesmo core do agente no backend
- as rotas `/web/auth/*` ficam ocultas com `404` enquanto `ENABLE_WEB_WHATSAPP_AUTH=false`

## WhatsApp OTP V1A

Objetivo:

- permitir que o usuario vincule a sessao web anonima a uma identidade verificada por WhatsApp
- preservar o chat anonimo V0 enquanto a autenticacao evolui em paralelo
- testar o contrato localmente antes de ativar adapter real de entrega

Rotas:

- `POST /web/auth/whatsapp/start` recebe `{"phone":"+5511999999999"}` e retorna `202` com `challenge_id`, `status`, TTL e cooldown
- `POST /web/auth/whatsapp/confirm` recebe `{"challenge_id":"uuid","code":"123456"}` e retorna `{"status":"verified","phone_last4":"9999"}`
- `GET /web/auth/session` retorna `{"status":"anonymous"}` ou a identidade verificada mascarada
- `POST /web/auth/logout` remove o vinculo da sessao e retorna `{"status":"anonymous"}`

Regras:

- telefone deve usar formato E.164
- OTP possui seis digitos, TTL configuravel, cooldown de reenvio e limite de tentativas
- erros de confirmacao usam apenas `invalid_or_expired_code`, sem revelar se o desafio existe
- telefone bruto, OTP e cookie nao entram em logs
- `IDENTITY_HASH_SECRET` e `OTP_DIGEST_SECRET` sao obrigatorios, privados e diferentes quando a feature flag estiver ativa
- `WEB_AUTH_STORAGE_BACKEND=memory` permanece apenas para laboratorio e perde
  vinculos ao reiniciar; `WEB_AUTH_STORAGE_BACKEND=postgres` preserva o estado
  por restart
- PostgreSQL, outbox e ingress assinado estao implementados sem alterar o
  contrato HTTP publico; entrega real por Meta ou Hermes ainda exige ativacao
  opt-in e smoke privado

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
- O valor deve usar apenas letras, numeros, `.`, `_`, `:`, `-` e nao pode
  parecer segredo, token, cookie, senha ou texto livre.
- Todas as respostas retornam `X-Request-ID`.
- Erros HTTP tratados tambem retornam `request_id` no corpo.
- O `request_id` do `/chat` deve ser preservado para envio posterior no `/feedback`.
- No website, o mesmo principio vale para `/web/chat` e `/web/feedback`: a UI deve preservar `request_id` como codigo de suporte e correlacao.

## `POST /web/chat`

Objetivo:

- expor uma fachada publica controlada para o website
- permitir uso da V0 do chat sem enviar segredo para o navegador
- manter o mesmo core de orquestracao do `/chat`

Entrada minima:

```json
{
  "message": "Como conectar o WhatsApp pela Meta API oficial?"
}
```

Validacoes:

- `message`: obrigatorio, sem branco puro, maximo 4000 caracteres
- campos extras sao rejeitados com `422`
- `domain` nao e aceito no V0 pela superficie publica
- `session_id` nao e aceito no payload do navegador; a sessao e resolvida pelo backend via cookie

Saida atual:

```json
{
  "request_id": "uuid",
  "answer": "resposta ao usuario",
  "escalated": false,
  "handoff_reasons": [],
  "references": ["qrcode-whatsapp.md"],
  "support_code": "uuid",
  "error_code": null
}
```

Regras operacionais:

- a rota usa cookie de sessao anonima `HttpOnly`
- o browser nao envia `X-API-Key`
- `support_code` replica `request_id` como codigo de suporte amigavel para UI
- `confidence` e `domain` continuam internos ao backend e nao fazem parte do contrato publico V0
- se `escalated=true`, a UI deve tratar isso como sinal de revisao humana ou necessidade de continuidade operacional, nao como falha silenciosa

Fronteira de responsabilidade:

- esta fachada publica nao substitui `/chat` ou webhooks dedicados para Meta
  WhatsApp e outros consumidores servidor-servidor
- o contrato interno protegido continua sendo a interface oficial para consumidores servidor-servidor

## `POST /web/feedback`

Objetivo:

- aceitar feedback do website sem expor segredo
- preservar contexto basico da resposta original do chat publico

Entrada minima:

```json
{
  "request_id": "uuid-retornado-pelo-chat",
  "helpful": true,
  "reason": "resolved",
  "comment": "A resposta ajudou."
}
```

Validacoes:

- `request_id`: obrigatorio, maximo 80 caracteres e formato seguro de correlacao
- `helpful`: obrigatorio
- `reason`: opcional, maximo 120 caracteres
- `comment`: opcional, maximo 500 caracteres
- campos extras sao rejeitados com `422`
- `session_id` nao vem do navegador; o backend resolve pela sessao anonima
- `source` e fixado no backend como `web`

Saida atual:

```json
{
  "feedback_id": "uuid",
  "accepted": true,
  "status": "accepted",
  "storage": "pending_persistence"
}
```

Regras operacionais:

- a rota reutiliza o contrato interno de feedback, mas restringe o shape publico
- o browser nao envia `X-API-Key`
- com `PERSISTENCE_BACKEND=postgres`, o feedback publico recebe confirmacao
  somente depois do commit; sem PostgreSQL, retorna `pending_persistence`

## `POST /chat`

Entrada minima:

```json
{
  "domain": "suporte-vps-whatsapp",
  "session_id": "whatsapp:+5511999999999",
  "channel": "whatsapp",
  "message": "Como conectar o WhatsApp pela Meta API oficial?"
}
```

Validacoes:

- `message`: obrigatorio, sem branco puro, maximo 4000 caracteres.
- `session_id`: opcional, maximo 160 caracteres, branco vira `null`.
- `domain`: opcional, maximo 80 caracteres, branco vira `null`.
- `channel`: opcional, somente `api` ou `whatsapp`; padrao `api`.
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
  "error_code": null,
  "handoff_status": "handoff_not_required",
  "persistence_status": "persisted"
}
```

`handoff_status` existe somente no contrato interno protegido e pode ser
`handoff_not_required`, `handoff_queued` ou `handoff_unavailable`. O campo
separa a decisao de escalar da confirmacao de que a notificacao foi enfileirada.

`persistence_status` pode ser `persisted`, `persistence_disabled` ou
`persistence_unavailable`. Se um handoff nao puder ser gravado na outbox,
`handoff_status=handoff_unavailable` e a resposta informa que o atendimento
humano esta temporariamente indisponivel.

Uso esperado:

- consumidores servidor-servidor legados ou internos podem enviar mensagens
  externas para este endpoint.
- esses consumidores devem enviar tambem `X-API-Key` quando consumirem esta
  rota.
- a `/chat-ui` pode enviar `X-LLM-API-Key` em staging para permitir que cada pessoa teste com a propria chave do provider ou com o alias do projeto.
- Se `escalated=true`, o consumidor deve preservar a decisao, mas nao duplicar
  a notificacao humana: a outbox e o workflow `escalation-notify` formam o
  caminho autoritativo.
- `request_id` deve ser preservado em logs e feedback.
- A API retorna `references`; na persistencia PostgreSQL, este campo deve ser salvo em `messages.message_references`.

Para detalhes operacionais da fundacao Meta, use
`docs/runbooks/meta-whatsapp-private-smoke.md`. O runbook
`docs/runbooks/n8n-whatsapp-chat-contract.md` permanece apenas como referencia
legada.

Contrato atual de `references`:

- hoje a API retorna uma lista de fontes rastreaveis do retrieval atual
- no estado atual do MVP, essas fontes costumam ser caminhos de arquivo em `domains/.../knowledge/...`
- com `RETRIEVAL_BACKEND=pgvector`, essas fontes continuam serializadas como
  caminhos rastreaveis de conhecimento versionado, preservando o contrato
  publico mesmo quando a busca vem do PostgreSQL
- na persistencia relacional, esse mesmo campo continua serializavel em JSON sem quebrar consumidores
- o contrato que outras frentes devem assumir hoje e `list[str]`
- se no futuro o backend passar a carregar metadados mais ricos de retrieval, isso deve entrar em um campo novo ou versao nova de contrato, sem quebrar `references`

Contrato atual de `handoff_reasons`:

- retorna motivos estruturados como `low_confidence`, `explicit_human_request`, `sensitive_topic`, `secret_request`, `prompt_injection_attempt` e `out_of_scope`
- integracoes externas nao devem inferir regra propria de negocio a partir do texto da resposta quando esse campo ja existir
- se `escalated=true`, o consumidor deve priorizar `handoff_reasons` para roteamento operacional

Contrato de persistencia de resposta:

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
- o armazenamento em PostgreSQL, indices e tabelas fica na frente do Renan
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
  "source": "integration",
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
- `request_id` e `message_id` aceitam somente identificadores de correlacao
  seguros; PII, IP, texto livre e prefixos reconheciveis de segredo sao
  rejeitados.
- `source` fora da allowlist `web`, `api`, `n8n` e `integration` vira `other`;
  `n8n` permanece aceito apenas por compatibilidade de eventos historicos.

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
- Com `PERSISTENCE_BACKEND=postgres`, a resposta usa `storage="postgres"` e
  `status="matched"` ou `status="orphan"` somente depois do commit.
- Com persistencia desativada, a resposta continua indicando
  `pending_persistence` para laboratorio. Esse estado nao representa commit.
- esta rota tambem exige `X-API-Key`.

Contrato de persistencia:

- `request_id` deve apontar para a resposta original do `/chat` quando existir
- se o mesmo `request_id` apontar para mais de um turno, o feedback fica
  `orphan` em vez de assumir silenciosamente um contexto incorreto
- `session_id` deve ser tratado como dado sensivel fora da API
- `message_id` continua opcional para permitir integracoes que ainda nao tenham
  ID interno de mensagem; quando enviado, torna retries do mesmo feedback
  idempotentes
- `helpful`, `reason`, `comment` e `source` devem continuar serializaveis sem conversao especial
- `escalated`, `handoff_reasons`, `references` e `error_code` podem ser
  reenviados apenas para comparacao; a persistencia recupera esses campos da
  resposta original no servidor e registra divergencia sem aceitar o cliente
  como fonte confiavel

Shape minimo persistido:

- `request_id`
- `session_hash` HMAC versionado, nunca `session_id` bruto
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
- O objetivo e revisar chunking e qualidade do conteudo antes de rodar ingestao
  persistente no pgvector.
- esta rota exige `X-API-Key` porque aceita payload livre e pode consumir recursos de processamento

Contrato preparatorio para retrieval e ingestao futura:

- `domain`, `source`, `title`, `text` e `chunk_index` devem continuar como campos basicos de interoperabilidade
- o backend atual nao promete IDs persistidos de chunk nesta rota
- a ingestao persistente por script operacional pode gravar artigos, chunks e
  embeddings no pgvector sem alterar este contrato de preview
- IDs persistidos e metadados extras devem complementar esse payload em uma
  evolucao futura, sem quebrar os campos atuais

Fronteira de responsabilidade:

- Renan pode evoluir o contrato HTTP e os testes de contrato
- Renan continua dono de schema, migrations, indices e persistencia final
  de banco
- Juliano pode evoluir splitter e loaders sem quebrar o shape HTTP acordado aqui

## `GET /ingestion/{domain_name}/preview`

Objetivo:

- Ler os arquivos locais ja existentes em `domains/<domain_name>/knowledge`.
- Retornar uma previa de documentos e chunks encontrados.

Uso esperado:

- Smoke test local do dominio.
- Conferencia rapida antes de rodar ingestao persistente no futuro.

Regra de seguranca:

- esta rota exige `X-API-Key`
- a previa existe para operadores autenticados e nao deve ser exposta publicamente em staging ou producao

## Ingress interno assinado para outbox

Endpoint:

```http
POST /internal/webhooks/outbox/{event_type}
```

Eventos aceitos:

- `handoff.requested`
- `whatsapp.message.requested`
- `otp.delivery.requested`

Headers obrigatorios:

```http
X-Idempotency-Key: <chave-estavel>
X-Webhook-Timestamp: <unix-seconds>
X-Webhook-Signature: sha256=<hmac>
```

Regras:

- fica oculto com `404` enquanto `ENABLE_OUTBOX_INGRESS=false`;
- valida HMAC sobre `timestamp + "." + raw_body`;
- rejeita timestamp fora da janela de cinco minutos;
- persiste somente hashes do payload e da chave idempotente, alem de metadados
  de entrega;
- duplicata ja entregue retorna `status=duplicate`;
- mesma chave com payload diferente retorna `409`;
- entrega concorrente em andamento retorna `425`;
- somente depois da validacao encaminha ao destino verificado configurado como
  `VERIFIED_*_WEBHOOK_URL`;
- `N8N_VERIFIED_*_URL` permanece como alias legado temporario para runtimes
  privados existentes;
- payload, assinatura, secret e URL privada nunca entram nos logs.

O dispatcher deve apontar `HANDOFF_WEBHOOK_URL`,
`WHATSAPP_MESSAGE_WEBHOOK_URL` e `OTP_DELIVERY_WEBHOOK_URL` para essa fachada
interna, nao diretamente para o n8n.

O dispatcher separa evento interno de rota de entrega:

- `handoff.requested` usa a rota `handoff`;
- `whatsapp.message.requested` usa a rota `whatsapp_message`;
- `otp.delivery.requested` usa a rota `otp_delivery`;
- as variaveis `OUTBOX_*_DELIVERY_TRANSPORT` controlam o transporte da rota;
- `internal_webhook` preserva o caminho atual assinado;
- `meta_whatsapp` entrega `whatsapp.message.requested` diretamente pela Meta
  Cloud API usando `META_WHATSAPP_ACCESS_TOKEN`,
  `META_WHATSAPP_PHONE_NUMBER_ID` e `META_WHATSAPP_GRAPH_API_VERSION`;
- `meta_whatsapp` e permitido somente para a rota `whatsapp_message`; handoff
  e OTP continuam por adapters/rotas proprias para evitar provedor errado;
- `disabled` desliga a rota de forma explicita e permanente, sem retry cego.

Payload minimo para `whatsapp.message.requested` com
`OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT=meta_whatsapp`:

```json
{
  "to": "5511999999999",
  "text": "Resposta segura."
}
```

Regras:

- `to` e `text` sao obrigatorios e devem ser strings nao vazias;
- o dispatcher nao aceita aliases ambiguos como `body` ou `phone`;
- o preflight `meta-outbox-message` valida a configuracao minima para este
  caminho sem imprimir token, phone number ID ou payload;
- erro 4xx definitivo da Meta vira dead letter, exceto status retryable como
  `408`, `409`, `425` e `429`;
- token, telefone e corpo da mensagem nao devem aparecer em log operacional.

## Webhook Meta WhatsApp Cloud API

Status: fundacao nativa implementada por feature flag, sem ativacao operacional
real nesta etapa.

Endpoint:

```http
GET /integrations/meta/whatsapp/webhook
POST /integrations/meta/whatsapp/webhook
```

Feature flag:

- fica oculto com `404` enquanto `ENABLE_META_WHATSAPP_WEBHOOK=false`.

Verificacao `GET`:

- aceita `hub.mode=subscribe`;
- compara `hub.verify_token` com `META_WHATSAPP_WEBHOOK_VERIFY_TOKEN`;
- devolve `hub.challenge` em texto puro quando a verificacao e valida;
- token incorreto retorna `403 meta_webhook_verification_failed`.

Recebimento `POST`:

- exige `X-Hub-Signature-256`;
- valida HMAC SHA-256 usando `META_WHATSAPP_APP_SECRET`;
- rejeita assinatura invalida com `401 invalid_meta_webhook_signature`;
- rejeita payload vazio, grande demais ou JSON invalido sem logar o corpo;
- parseia apenas mensagens de texto e status de mensagem;
- responde `{"status":"accepted"}` quando a assinatura e o payload minimo sao
  aceitos.

Eventos normalizados nesta fundacao:

- `messages[].type="text"` vira mensagem inbound normalizada;
- `statuses[]` vira status normalizado de mensagem outbound;
- anexos, imagens, audio, documentos, contatos e localizacao ainda nao fazem
  parte do contrato interno.

Campos e dados proibidos em log:

- telefone bruto;
- `wa_id` bruto;
- corpo da mensagem;
- payload completo;
- token de acesso;
- app secret;
- verify token.

Proxima etapa:

- ativar mensagens inbound pelo `MetaWhatsAppChatTransport` em smoke privado;
- ativar OTP por `MetaWhatsAppOtpDeliveryAdapter` em smoke privado;
- manter o core RAG sem conhecer payload bruto da Meta.

## Chat WhatsApp Por Meta

Status: transport implementado e desativado por padrao.

Feature/config:

- `ENABLE_META_WHATSAPP_CHAT=false` preserva o webhook Meta apenas como
  recebimento/parsing;
- `ENABLE_META_WHATSAPP_CHAT=true` conecta mensagens inbound de texto ao core de
  chat e envia a resposta pela Meta;
- quando `ENABLE_META_WHATSAPP_CHAT=true`, `META_WHATSAPP_ACCESS_TOKEN` e
  `META_WHATSAPP_PHONE_NUMBER_ID` sao obrigatorios.

Regras:

- somente mensagens de texto entram no fluxo inicial;
- payload bruto da Meta nao e passado para o core;
- `wa_id` bruto nao e usado como `session_id` persistido;
- `channel` continua `whatsapp`;
- handoff, confidence, references e `error_code` continuam decididos pelo core;
- falhas de dominio ou envio externo retornam erro tecnico rastreavel sem
  expor payload ou token.

## Entrega OTP Por Meta WhatsApp

Status: adapter implementado e desativado por padrao.

Feature/config:

- `WEB_AUTH_OTP_DELIVERY_TRANSPORT=memory` preserva o laboratorio local;
- `WEB_AUTH_OTP_DELIVERY_TRANSPORT=meta` ativa o adapter Meta para o fluxo
  `/web/auth/whatsapp/start`;
- quando `ENABLE_WEB_WHATSAPP_AUTH=true` e o transporte e `meta`, os campos
  `META_WHATSAPP_ACCESS_TOKEN`, `META_WHATSAPP_PHONE_NUMBER_ID` e
  `META_WHATSAPP_OTP_TEMPLATE_NAME` sao obrigatorios.

Regras:

- o backend continua dono do OTP, TTL, cooldown, tentativas e validacao;
- o adapter apenas entrega o template aprovado pela Meta;
- falha externa retorna `otp_delivery_unavailable` no contrato publico;
- erro bruto da Meta, telefone bruto, OTP e token nao entram em log.

## Entrega OTP Por Hermes

Status: adapter temporario implementado e desativado por padrao.

Feature/config:

- `WEB_AUTH_OTP_DELIVERY_TRANSPORT=hermes` ativa Hermes apenas para entrega de
  OTP do fluxo `/web/auth/whatsapp/start`;
- `HERMES_BASE_URL`, `HERMES_WEBHOOK_SECRET`, `HERMES_REQUEST_TIMEOUT_SECONDS`
  e `HERMES_OTP_DELIVERY_PATH` configuram o transporte;
- o default continua `WEB_AUTH_OTP_DELIVERY_TRANSPORT=memory`.

Contrato enviado ao Hermes:

```json
{
  "delivery_id": "challenge-id",
  "channel": "whatsapp",
  "phone_e164": "+5511999999999",
  "chat_id": "5511999999999@s.whatsapp.net",
  "template": "web_login_otp",
  "variables": {
    "code": "123456",
    "expires_in_minutes": 5
  }
}
```

Headers:

```http
X-Delivery-ID: <challenge-id>
X-Webhook-Timestamp: <unix-seconds>
X-Webhook-Signature: sha256=<hmac>
```

Regras:

- Hermes apenas transporta mensagem;
- backend continua dono do OTP, TTL, cooldown, tentativas e validacao;
- `chat_id` e enviado para compatibilidade com bridges que exigem o
  identificador interno de entrega do WhatsApp; `phone_e164` continua sendo o
  telefone canonico do contrato e deve permanecer em formato E.164;
- Hermes nao acessa banco, prompt, RAG, handoff ou regras de dominio;
- erro externo vira `otp_delivery_unavailable` no contrato publico;
- telefone bruto e OTP circulam somente no canal servidor-servidor protegido e
  nao devem aparecer em logs.

## `POST /zoom/webhook`

Objetivo:

- receber callbacks controlados do bot de reuniao
- disparar processamento assinado do chat recebido sem expor o endpoint para trafego anonimo

Autenticacao aceita:

- `X-API-Key` para chamadas internas controladas
- query param `token` quando igual ao segredo privado configurado em `ZOOM_WEBHOOK_SECRET`

Regras:

- chamadas sem `X-API-Key` valida ou sem `token` valido retornam `403`
- quando `ZOOM_WEBHOOK_SECRET` estiver configurado, `POST /zoom/join` anexa esse segredo ao `webhook_url` enviado ao Recall/Zoom
- o backend nao deve logar payload bruto do webhook, mensagem completa, nomes reais de participantes ou segredos
- falhas do provider em `POST /zoom/join` retornam apenas
  `zoom_provider_unavailable` ou `zoom_provider_rejected_request`, nunca o
  corpo bruto do provider
