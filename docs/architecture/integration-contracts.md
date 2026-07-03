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

- `POST /web/auth/whatsapp/start` recebe `{"phone":"+5511999999999"}` e retorna
  `202` com `challenge_id`, `status`, TTL, cooldown e
  `abandonment_reminder_seconds` (Sprint 4b: janela sugerida, hoje 15 min, para
  o widget mostrar um lembrete local de "ainda não recebeu?" — não existe job
  de lembrete no backend, ver seção do gate de consentimento abaixo)
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
- em PostgreSQL, a identidade verificada pode ser vinculada a um `customer_id`
  interno para historico, preferencias e suporte humano; esse identificador
  nao faz parte do contrato publico do navegador nesta etapa

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

## `POST /web/handoff/consent` (gate de consentimento LGPD, Sprint 4b)

Status: implementado, dark por `ENABLE_HANDOFF_CONSENT_GATE` (default `false`;
oculto com `404` quando desligado). Requer `ENABLE_WEB_WHATSAPP_AUTH=true`
(validado em `Settings`, falha no boot se não estiver).

Objetivo:

- autorizar a equipe a contatar diretamente o cliente do **web chat** (que
  chega anônimo) só depois que ele confirma o WhatsApp via OTP — não é sobre
  identidade em geral, é consentimento explícito no momento do handoff
- WhatsApp nativo (Hermes/Meta) fica **fora** deste gate: o número já é
  conhecido pelo próprio canal e a equipe responde na mesma conversa que o
  cliente iniciou, não é contato novo

Fluxo:

1. `POST /web/chat` responde `escalated: true` (comportamento já existente,
   inalterado) — o widget mostra um convite local para conectar com humano.
2. Se o cliente aceitar: `POST /web/auth/whatsapp/start` +
   `POST /web/auth/whatsapp/confirm` (rotas já existentes, sem mudança de
   contrato) confirmam o WhatsApp.
3. `POST /web/handoff/consent` com `{"request_id": "<do turno escalado>", "name": "...", "email": "..."}`.

Entrada:

```json
{ "request_id": "uuid-do-turno-escalado", "name": "Renan", "email": "renan@example.com" }
```

- `request_id`: obrigatório, o mesmo já devolvido pelo `/web/chat` daquele turno.
- `name`/`email`: opcionais; gravados em `customers` só se ainda não
  preenchidos (primeira vez vence — não sobrescreve dado já existente,
  reaproveitado em tickets futuros do mesmo cliente).

Saída (`200`):

```json
{ "support_case_id": "uuid", "status": "open", "opened_at": "2026-07-01T00:00:00+00:00", "summary": "...", "domain": "suporte-vps-whatsapp", "customer_name": "Renan" }
```

- `customer_name`: nome **efetivo** no registro do cliente após a promoção (um
  consent anterior vence um redigitado, pelo `COALESCE`), para o widget espelhar
  ao cliente exatamente o que foi dito ao time. `null` no replay idempotente e
  quando nenhum nome existe.

Erros:

- `401 otp_confirmation_required`: sessão ainda não autenticada — nunca deixa
  chegar a um `support_case` sem OTP confirmado.
- `404 support_case_not_found`: `request_id` não corresponde a um caso
  `pending_consent` do `customer_id` da sessão. Usado tanto para "não existe"
  quanto para "pertence a outro cliente" — nunca revela qual dos dois é o caso
  real.
- `422 invalid_email`: formato de e-mail inválido.
- `503 handoff_consent_storage_unavailable`: banco indisponível; idempotente,
  tentar de novo depois.

Contrato de dados (decisão de arquitetura importante):

- o `support_case` **já nasce** na mesma transação do turno escalado, como
  sempre (preserva a garantia "nenhum turno escalado fica sem ticket") — o que
  muda é o status inicial: `pending_consent` em vez de `open` quando o gate
  está ativo (e o canal é `web`; WhatsApp nativo sempre nasce `open`)
- o que fica **adiado** até este endpoint é só a notificação ao time
  (`whatsapp.message.requested`) e o evento `handoff.requested` na outbox —
  nunca a criação do caso em si
- a notificação adiada sai **enriquecida com o contato autorizado**: linhas
  `Cliente: <nome>`, `Contato autorizado (LGPD): <e-mail>` e
  `WhatsApp verificado: final <last4>` quando presentes. O e-mail aparece
  legível **só** nesse alerta interno ao time e no registro `customers` — nunca
  em payload sanitizado, log ou superfície pública. O canal WhatsApp nativo não
  passa por aqui e segue sem bloco de contato (a equipe responde na própria
  thread)
- reprocessar o mesmo `request_id` depois de já promovido é idempotente
  (retorna o estado atual, não duplica notificação)
- migration `013_customer_contact_and_consent.sql`: adiciona `customers.email`
  e o valor `pending_consent` ao `CHECK` de `support_cases.status`

Superfície de leitura afetada — `GET /internal/support-cases` (inbox do time):
sem filtro explícito de `status`, casos `pending_consent` **nunca** aparecem
por padrão (ver seção do inbox abaixo); só aparecem com
`?status=pending_consent` explícito, para depuração.

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

`escalated=true` **nao garante por si so** uma entrada na fila humana. Quando a
flag por dominio `soft_low_confidence` esta ligada (WS-3), um turno cujo unico
motivo e `low_confidence` permanece `escalated=true` e registrado, mas **nao**
gera `support_case` nem evento `handoff.requested` (`handoff_status=handoff_not_required`).
A fila humana e acionada por motivos nao-soft (pedido humano explicito, tema
sensivel, segredo, dado de cartao, regra de escalonamento do dominio, erro de
provider, etc.). Com a flag desligada (default), o comportamento legado se mantem:
qualquer `escalated=true` enfileira. Consumidores devem usar `handoff_status`, nao
`escalated`, para decidir se um humano foi acionado.

`persistence_status` pode ser `persisted`, `persistence_disabled` ou
`persistence_unavailable`. Quando `escalated=true` e a persistencia PostgreSQL
esta ativa, o backend cria ou reutiliza um `support_case` duravel antes de
enfileirar a entrega externa. Se o caso ou a outbox nao puderem ser gravados,
`handoff_status=handoff_unavailable` e a resposta informa que o atendimento
humano esta temporariamente indisponivel.

Uso esperado:

- consumidores servidor-servidor legados ou internos podem enviar mensagens
  externas para este endpoint.
- esses consumidores devem enviar tambem `X-API-Key` quando consumirem esta
  rota.
- a `/chat-ui` pode enviar `X-LLM-API-Key` em staging para permitir que cada pessoa teste com a propria chave do provider ou com o alias do projeto.
- Se `escalated=true`, o consumidor deve preservar a decisao, mas nao duplicar
  a notificacao humana: `support_cases` e a fonte de verdade do ticket humano,
  e a outbox e o caminho autoritativo de entrega externa.
- `request_id` deve ser preservado em logs e feedback.
- A API retorna `references`; na persistencia PostgreSQL, este campo deve ser salvo em `messages.message_references`.

Para detalhes operacionais da fundacao Meta, use
`docs/runbooks/meta-whatsapp-private-smoke.md`. O contrato historico n8n/WhatsApp
foi arquivado em `docs/archive/runbooks/n8n-whatsapp-chat-contract.md` apos a
remocao do n8n; consulte apenas como referencia legada.

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

Contrato atual de `support_cases`:

- o caso humano e criado dentro da mesma transacao da persistencia do chat
  escalado;
- `support_cases.idempotency_key` impede duplicidade no retry do mesmo turno;
- `context_snapshot_sanitized` guarda apenas resumo, referencias, motivos e
  erro sanitizados;
- o evento `handoff.requested` na outbox inclui `support_case_id` no
  `payload_sanitized`;
- outbox continua sendo fila de entrega, nao banco de ticket.

Notificacao WhatsApp para o time (Sprint 5):

- dark por padrao: so dispara com `ENABLE_SUPPORT_TEAM_WHATSAPP_NOTIFY=true` e
  `SUPPORT_TEAM_WHATSAPP_RECIPIENTS` preenchido (lista separada por virgula de
  numeros internos verificados);
- na mesma transacao que cria o `support_case`, o handoff enfileira um evento
  `whatsapp.message.requested` por destinatario interno, alem do
  `handoff.requested`;
- a renderizacao do alerta e best-effort: se falhar, o ticket e o
  `handoff.requested` continuam gravados (a notificacao nunca derruba o caso);
- idempotencia por turno + destinatario (`support_notify:<turn_id>:<hash>`), entao
  retry do mesmo turno nao duplica alerta;
- o texto do alerta usa apenas campos ja sanitizados (caso, dominio, motivos,
  resumo, referencias); o numero `to` do destinatario interno e gravado verbatim
  para a entrega e por isso nao passa por `sanitize_payload`;
- a entrega real usa a rota `whatsapp_message` ja existente; defina
  `OUTBOX_WHATSAPP_MESSAGE_DELIVERY_TRANSPORT=meta_whatsapp` para enviar e
  `disabled` para manter os eventos apenas auditaveis sem enviar.

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

Resposta:

- Mesmo shape de `POST /ingestion/preview`: `domain`, `document_count`,
  `chunk_count`, `sample_chunks` e a lista completa `chunks` com `source`,
  `title`, `text` e `chunk_index`.
- `source` aponta para o caminho local do arquivo lido em
  `domains/<domain_name>/knowledge`.
- Como nao recebe payload via header, normalmente nao envia `request_id`.
- Tambem nao persiste dados nem gera embeddings.

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
- payload, assinatura, secret e URL privada nunca entram nos logs.

O dispatcher deve apontar `HANDOFF_WEBHOOK_URL`,
`WHATSAPP_MESSAGE_WEBHOOK_URL` e `OTP_DELIVERY_WEBHOOK_URL` para essa fachada
interna de entrega verificada, nao diretamente para um provedor externo.

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

## Inbox interno de support cases

Status: superficie de leitura para o time de atendimento ver e triar tickets
durables de handoff com contexto rico. Dark por padrao: so responde quando
`ENABLE_SUPPORT_INBOX=true`; com a flag desligada as rotas retornam `404`.

```text
GET /internal/support-cases
GET /internal/support-cases/{case_id}
```

Objetivo:

- entregar a "ponta de integracao" do fluxo de handoff: o ticket durable
  (`support_cases`, migration 009) ja existe, mas nao havia superficie para o
  time ler/triar nem o contexto organizado da conversa.
- montar o contexto rico on-read seguindo `support_cases.conversation_id` ate o
  transcript ja sanitizado em `messages`. Nada e re-persistido nem
  re-sanitizado; o builder so organiza valores ja sanitizados na escrita.

Autenticacao e gating:

- exige `X-API-Key` (mesmo segredo das demais rotas internas);
- exige `ENABLE_SUPPORT_INBOX=true`; caso contrario `404`.

`GET /internal/support-cases` (lista/triagem):

- query params: `domain` (opcional, max 80), `status` (opcional, um de
  `open|in_progress|waiting_customer|closed|cancelled|pending_consent`; valor
  invalido vira `422`), `limit` (1..100, padrao 25), `offset` (>= 0, padrao 0);
- ordenado por `opened_at DESC`, usando o indice
  `idx_support_cases_domain_status_opened`.
- **Sprint 4b**: sem `status` explicito, casos `pending_consent` (aguardando
  confirmacao de LGPD do cliente no web chat, ver `POST /web/handoff/consent`)
  **nunca** aparecem — o time so os ve pedindo `?status=pending_consent`
  explicitamente. Existe pra nao vazar contexto de um caso antes do cliente
  autorizar o contato.

Saida da lista:

```json
{
  "request_id": "uuid-ou-header",
  "count": 1,
  "limit": 25,
  "offset": 0,
  "cases": [
    {
      "case_id": "uuid",
      "domain": "suporte-vps-whatsapp",
      "status": "open",
      "priority": "normal",
      "channel": "whatsapp",
      "request_id": "req-do-turno",
      "reason_codes": ["low_confidence"],
      "summary": "resumo curto do snapshot",
      "turn_count": 9,
      "opened_at": "2026-06-28T00:00:00Z",
      "updated_at": "2026-06-28T00:00:00Z"
    }
  ]
}
```

`turn_count` vem do bloco `organized_context` do snapshot (ver abaixo) e e `null`
para casos antigos gravados antes do enriquecimento.

`GET /internal/support-cases/{case_id}` (detalhe com transcript):

- `404` (`support_case_not_found`) quando o caso nao existe;
- transcript ordenado por `message_sequence ASC`, limitado a 200 turns, apenas
  papeis `user`/`assistant` na `redaction_version` corrente;
- `references` e a uniao ordenada e deduplicada das referencias do snapshot e de
  cada turn;
- `customer` e o bloco de contato que o cliente autorizou no gate LGPD
  (`POST /web/handoff/consent`), lido on-read via `LEFT JOIN customers` +
  identidade verificada mais recente (fonte unica de verdade — um replay de
  turno que sobrescreva o snapshot do caso nunca perde o contato). `null`
  quando o caso nao tem `customer_id` (ex.: WhatsApp nativo). O e-mail e
  legivel de proposito — o time usa para contato real — e so aparece nesta
  superficie interna autenticada.

Saida do detalhe (resumida):

```json
{
  "request_id": "uuid-ou-header",
  "case_id": "uuid",
  "domain": "suporte-vps-whatsapp",
  "status": "open",
  "priority": "normal",
  "channel": "whatsapp",
  "case_request_id": "req-do-turno",
  "reason_codes": ["low_confidence"],
  "summary": "resumo curto do snapshot",
  "references": ["kb:vps-restart", "kb:handoff"],
  "turn_count": 2,
  "opened_at": "2026-06-28T00:00:00Z",
  "updated_at": "2026-06-28T00:00:00Z",
  "customer": {
    "display_label": "Renan",
    "email": "renan@example.com",
    "phone_last4": "1234"
  },
  "transcript": [
    {
      "sequence": 1,
      "role": "user",
      "content": "texto sanitizado",
      "confidence": null,
      "escalated": false,
      "handoff_reasons": [],
      "references": [],
      "error_code": null,
      "created_at": "2026-06-28T00:00:00Z"
    }
  ]
}
```

Observacoes:

- `DatabaseUnavailableError` vira `503` (`support_inbox_storage_unavailable`);
- logs operacionais carregam apenas contagens e identificadores seguros
  (`case_id`, `request_id`, `status`, `turn_count`); nunca conteudo de turn,
  `session_hash` ou PII;
- o montador `app/support/context.py` e o seam reusavel entre read e push: o
  read serve o transcript completo on-read; o write path do handoff
  (`operational.py`) reusa os mesmos primitivos via
  `app/support/transcript.py:build_support_snapshot_context` para gravar um bloco
  `organized_context` limitado.

Enriquecimento `organized_context` (Fase B, push):

- gravado em `support_cases.context_snapshot_sanitized` e tambem no payload
  `handoff.requested` da outbox, para read e push descreverem o handoff de forma
  identica;
- limitado para caber no orcamento do webhook (`MAX_BODY_BYTES` 65536): no maximo
  `SNAPSHOT_MAX_TURNS=12` turns recentes, cada `content` truncado em
  `SNAPSHOT_TURN_CONTENT_LIMIT=1000` caracteres;
- shape:

```json
{
  "turn_count": 23,
  "included_turn_count": 12,
  "references": ["kb:vps-restart"],
  "recent_turns": [
    { "sequence": 12, "role": "user", "content": "texto sanitizado" }
  ]
}
```

- `turn_count` e o total real da conversa; `included_turn_count` e quantos turns
  recentes foram embarcados (o read serve o restante on-read);
- **best-effort**: se a montagem do bloco falhar, o caso durable e o evento
  `handoff.requested` ainda sao gravados sem `organized_context` — a garantia
  "turno nao resolvido -> ticket durable" nunca enfraquece.

Fronteira de responsabilidade:

- Renan: contrato HTTP, repositorio de leitura, montador de contexto, testes;
- esta rota nao escreve em banco e nao altera o caminho de escrita do handoff
  (`operational.py`) nem o relay de outbox (`internal_webhooks.py`).

## Fachada web staff do console de suporte (`/web/support/*`)

Status: Fase A entregue (auth OTP staff dedicado + fila com semaforo, leitura).
Plano: `docs/quality-plans/support-team-console-tech-plan.md`. Dark por padrao:
so responde quando `ENABLE_SUPPORT_CONSOLE=true`; com a flag desligada toda a
superficie (inclusive auth) retorna `404`. Consumidor: a area interna `/team`
do `ask-host-genius`, same-origin — nenhum segredo, nenhum `X-API-Key`, nenhum
telefone bruto no JS do cliente.

```text
POST /web/support/auth/start
POST /web/support/auth/confirm
GET  /web/support/auth/session
POST /web/support/auth/logout
GET  /web/support/cases
GET  /web/support/cases/{case_id}
```

Autenticacao (OTP WhatsApp dedicado, staff nao e cliente):

- `POST /web/support/auth/start` — body `{ "phone": "+55..." }` (opcional
  quando o cookie de lembrete `sfa_staff_hint` esta presente). Responde `202`
  com `{ challenge_id, expires_in_seconds, retry_after_seconds }`.
  Anti-enumeracao: telefone fora de `staff_members` recebe o mesmo `202` com
  `challenge_id` sintetico; a resposta tambem nao varia com falha de entrega
  (vira log interno `support_console_auth_delivery_failed`). Cooldown de
  reenvio e rate limits proprios (`SUPPORT_OTP_START_*`) aplicados de forma
  identica para staff e nao-staff; excedido -> `429` com `Retry-After`.
  Sem telefone e sem lembrete valido -> `422 invalid_phone`.
- `POST /web/support/auth/confirm` — body `{ challenge_id, code, phone? }`.
  Sucesso: `{ display_name, expires_at }` + cookies `HttpOnly; Secure;
  SameSite=Lax`: `sfa_staff_session` (`Path=/web/support`, expira na proxima
  `SUPPORT_STAFF_SESSION_EXPIRY_HOUR` no fuso `SUPPORT_CONSOLE_TIMEZONE`; o
  servidor e a fonte de verdade, o `Max-Age` so acompanha) e `sfa_staff_hint`
  (`Path=/web/support/auth`, `SUPPORT_STAFF_HINT_TTL_DAYS`). Codigo
  invalido/expirado (inclusive challenge sintetico) -> `400
  invalid_or_expired_code`. O `phone` opcional e reenviado pela tela no
  primeiro acesso para vincular o lembrete: o cookie de lembrete carrega
  `<token>.<E.164>` e o telefone so e aceito se o HMAC bater com o
  `phone_hash` do staff dono do token — o banco nunca guarda telefone bruto e
  o lembrete sozinho so consegue disparar OTP para o numero registrado do
  proprio operador.
- `GET /web/support/auth/session` — `200 { authenticated: true, display_name,
  expires_at }` ou `401 { authenticated: false, hint: { display_name } | null }`
  (o `hint` habilita o botao de 1 clique "Entrar como <nome>"). E o guard de
  rota da UI.
- `POST /web/support/auth/logout` — body opcional
  `{ "forget_device": true }` remove tambem o lembrete; sem isso o lembrete
  sobrevive ao logout. Apaga a linha da sessao e expira o cookie.

`GET /web/support/cases` (fila com semaforo; exige sessao staff valida):

- query: `view` (`active` padrao | `history`), `domain`, `status` (mesmos
  valores do inbox interno; `pending_consent` so aparece com filtro
  explicito), `color` (`green|yellow|red|paused`), `sort` (`attention` padrao
  | `opened_at`), `limit` (1..100, padrao 25), `offset`;
- `active`: SQL so filtra e limita (`SUPPORT_CONSOLE_ACTIVE_CASES_CAP`, com
  `truncated: true` na resposta quando atingido); SLA, ordenacao "attention"
  (estourado-e-nao-pausado primeiro, depois peso de prioridade, depois mais
  antigo), filtro por cor e paginacao acontecem em Python sobre o relogio do
  banco (`now()` na mesma query — um relogio so);
- `history`: fechados/cancelados, paginacao SQL por `opened_at DESC`, sem SLA;
- resposta = resumo do inbox + blocos novos por caso:

```json
{
  "sla": {
    "deadline_at": "2026-07-02T18:00:00Z",
    "elapsed_ratio": 1.7,
    "color": "red",
    "paused": false,
    "explanation": "urgente, aberto há 6h12, prazo estourado há 5h12"
  },
  "assignee": null,
  "truncated": false
}
```

- `assignee` fica `null` ate a Fase B; casos pausados (`waiting_customer`,
  `pending_consent`) nunca ficam vermelhos e `paused: true` guia o chip neutro
  da UI.

`GET /web/support/cases/{case_id}`: igual ao detalhe do inbox interno
(transcript sanitizado, referencias, contato autorizado via consent gate) +
blocos `sla` (null para fechados/cancelados) e `assignee`.

Guardas e erros:

- toda rota fora de `auth/*` usa `require_staff_session`: cookie -> HMAC ->
  `staff_sessions` com `expires_at > now()` join `staff_members.status =
  'active'` (desativar um staff derruba as sessoes vivas no ato); falha ->
  `401` com detail generico; rate limit de leitura por sessao
  (`SUPPORT_CONSOLE_READS_PER_SESSION_PER_MINUTE`) -> `429`;
- banco indisponivel -> `503 support_inbox_storage_unavailable` (mesmo
  contrato do inbox interno);
- break-glass: `GET /internal/support-cases` com `X-API-Key` continua
  funcionando servidor-servidor se a entrega de OTP cair.

Observabilidade (sem PII, hashes truncados, nunca telefone/transcript/token):
`support_console_auth_started`, `support_console_auth_confirmed`,
`support_console_auth_delivery_failed`, `support_console_listed`,
`support_console_case_viewed`, `support_console_active_cap_reached`.

Gestao de operadores: `scripts/manage_staff.py add|disable|list` (usa
`DATABASE_URL` + `IDENTITY_HASH_SECRET`, nunca imprime telefone completo);
rotacao de `IDENTITY_HASH_SECRET` invalida os hashes staff e exige recadastro.

Fronteira de responsabilidade:

- Renan: contrato HTTP, auth staff, SLA, repositorio, migration 014, testes;
- Juliano: deploy da tela `/team` no `ask-host-genius` (mesmo fluxo do
  `deploy_ask_host_genius`); a UI nao recalcula regra de negocio.

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
X-Webhook-Signature: <hex-hmac-sha256-body>
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
- a assinatura generica do Hermes usa HMAC SHA-256 do corpo bruto no header
  `X-Webhook-Signature`, sem prefixo `sha256=`.

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


## Minion de diagnostico (dominio hospedagem)

Status: **contrato planejado, sem implementacao.** Escrito adiantado (2026-07-01)
para o Juliano construir contra uma interface travada, em vez de o contrato ser
extraido depois do script pronto. Origem: conversa registrada em
`docs/quality-plans/customer-identity-whatsapp-handoff-plan.md` ("Extensao futura
BLOQUEADA"). O minion em si (script bash, depois plugin cPanel/EasyPanel) e frente
do Juliano (VPS/externo); este contrato HTTP e frente do Renan.

Objetivo:

- permitir que um script/app rodando no servidor do **cliente** (dominio
  `suporte-hospedagem`) busque arquivos de configuracao ja sanitizados na origem
  (ex.: Dovecot, Postfix) e entregue ao agente para diagnostico, sem trafegar
  dado sensivel do cliente pela rede em nenhum momento.
- v1 e **somente leitura/diagnostico**. Acao de aplicar correcao (escrita no
  servidor do cliente) fica como extensao futura explicita (ver subsecao),
  **nao** faz parte deste contrato ainda — pendente de alinhamento entre Renan e
  Juliano sobre escopo leitura-vs-escrita da v1.

Duas camadas de confianca, nao confundir:

1. **Minion <-> agente** (maquina-a-maquina): o pairing token abaixo. Prova que
   quem chama e o script rodando no servidor daquele cliente especifico.
2. **Cliente <-> OTP** (humano): a autorizacao LGPD do Sprint 4b. Autoriza o
   *contato*/uso da informacao, nao substitui o pairing token.

### Pairing

O `ChatFlowService`, ao decidir (dominio `suporte-hospedagem`, confianca baixa
ou padrao que sugere problema de configuracao) que vale rodar o minion, gera um
**pairing token** de uso unico e devolve ao cliente **dentro da propria
resposta do chat** (nao e um endpoint separado que o navegador chama) — o texto
inclui o comando para o cliente rodar no servidor:

```
curl -fsSL https://.../minion.sh | bash -s -- --token=<pairing_token>
```

Regras do token:

- TTL curto (ex.: 15 min, mesma ordem de grandeza do OTP);
- uso unico — primeira chamada valida consome; reentrega usa o mesmo `manifest`
  idempotente, mas o `submit` so aceita uma vez por token;
- escopado a `(customer_ref, domain, request_id)` — nunca reaproveitavel entre
  conversas;
- nunca logado em texto puro (mesmo tratamento de `challenge_id`/segredo ja
  usado em `app/web_auth/`).

### `GET /internal/minion/{token}/manifest`

Objetivo: o minion pergunta o que o agente precisa.

Saida:

```json
{
  "domain": "suporte-hospedagem",
  "requested": [
    { "id": "dovecot-main", "hint": "arquivo de configuracao principal do Dovecot" },
    { "id": "postfix-main", "hint": "arquivo de configuracao principal do Postfix" }
  ]
}
```

Regras:

- `401` (`invalid_or_expired_pairing_token`) para token invalido/expirado/consumido —
  mesmo padrao de nao revelar detalhe de qual condicao falhou (espelha
  `invalid_or_expired_code` do OTP);
- lista de `requested` decidida pelo dominio/handoff, nao pelo minion — o minion
  nunca escolhe o que enviar, so responde ao que foi pedido;
- **nao** requer `X-API-Key` (o pairing token e a credencial desta rota, o
  chamador e externo ao dominio de rede protegido).

### `POST /internal/minion/{token}/submit`

Objetivo: o minion entrega o conteudo ja sanitizado na origem.

Entrada:

```json
{
  "files": [
    { "id": "dovecot-main", "path": "/etc/dovecot/dovecot.conf", "content_sanitized": "..." }
  ]
}
```

Regras:

- consome o token (uso unico) e enfileira o diagnostico — a resposta final vai
  para o **cliente**, pelo canal de chat normal (WhatsApp/web), nao de volta
  para o minion; este endpoint so confirma recebimento (`202`);
- **defesa em profundidade obrigatoria**: mesmo o minion alegando que ja
  sanitizou na origem, o backend roda `sanitize_payload`/deteccao de
  segredo/PAN de novo antes de qualquer conteudo ir ao prompt do modelo —
  mesmo principio ja aplicado no batch de sumarizacao (nunca confiar
  cegamente no upstream);
- `path` e metadado (para a resposta poder dizer "esse arquivo fica em
  ...") e nao deve, sozinho, ser tratado como PII, mas o log operacional
  registra apenas contagem de arquivos e `id`s, nunca `path`/`content`;
- limite de tamanho por arquivo e por request (mesmo espirito de
  `MAX_BODY_BYTES` ja usado no ingress assinado da outbox);
- token expirado/ja consumido -> `401`/`409`, sem detalhar motivo.

Campos e dados proibidos em log (mesma disciplina do webhook Meta):

- conteudo de arquivo, `path` bruto, pairing token bruto, qualquer segredo
  extraido do arquivo (senha, chave privada, connection string).

### Extensao futura (nao implementada): acoes sensiveis via OTP

Ideia registrada, **sem contrato fechado**: quando o agente propuser uma
correcao que exige escrita no servidor do cliente, o pairing token sozinho
**nao basta** — precisa da segunda camada (OTP do Sprint 4b) como confirmacao
explicita do cliente antes do minion aplicar a mudanca. Pendente de decisao:
Juliano queria a v1 do script bash restrita a leitura; essa extensao so faz
sentido depois desse alinhamento e, possivelmente, so para os adapters de
API de painel (cPanel/EasyPanel), nao para o script bash generico.

Fronteira de responsabilidade:

- Renan: contrato HTTP, pairing token, sanitizacao de entrada, ponte com o
  `ChatFlowService`/dominio `suporte-hospedagem`;
- Juliano: o minion em si (script bash, depois plugin cPanel/EasyPanel), coleta
  e sanitizacao na origem, distribuicao/instalacao no servidor do cliente;
- nenhuma logica de dominio (o que e "config valida", como corrigir) deve viver
  no minion — ele so busca e entrega, espelhando a regra ja aplicada a
  Hermes/Meta ("nao mover inteligencia para o transporte externo").

## Roteamento de dominio no WhatsApp (palavra-chave + saudacao natural)

Quando um unico numero WhatsApp atende mais de um dominio (por exemplo
`suporte-vps-whatsapp` e `vendas`), os transportes Meta e Hermes usam
`DomainRouter` (`app/orchestration/domain_router.py`) para decidir qual dominio
responde cada mensagem.

Contrato:

- desligado por padrao (`ENABLE_WHATSAPP_DOMAIN_ROUTER=false`); ligado, exige
  `WHATSAPP_ROUTER_DOMAINS` com 2+ dominios validos, na ordem de selecao
  (`1`, `2`, ...).
- selecao explicita por numero (`1`, `2`) ou pelo nome da opcao (`suporte`,
  `vendas`) segue funcionando como atalho e escolhe o dominio.
- sem selecao, a mensagem e pontuada contra `routing.keywords` de cada dominio
  (match por palavra inteira, acentos normalizados); o melhor unico vence.
- saudacao, texto vazio, empate ou nenhum match -> o transporte NAO chama o
  motor de resposta e envia o fallback conversacional
  (`fallback_routing_text` em `app/orchestration/channel_routing.py`):
  - primeiro contato: saudacao institucional (HostGator Brasil + assistente
    virtual + areas atendidas), que induz uma resposta roteavel;
  - resposta ainda ambigua apos a saudacao, ou reset explicito
    (`menu`/`trocar`/`voltar`): pergunta de esclarecimento
    ("suporte tecnico ou planos?");
  - esclarecimento repetido em sequencia: o dedup do transporte Hermes troca
    pelo nudge anti-loop existente.
  - o status de observabilidade desses turnos continua `routing_menu`
    (contrato preservado; so o texto mudou).
- a alternancia saudacao -> esclarecimento usa o ultimo texto enviado por
  sessao (`session_last_out_store`); no transporte Meta apenas os turnos de
  roteamento sao registrados nesse store.
- com 1 dominio configurado, nunca envia fallback (atende sempre esse dominio).
- o `DomainRouter` em si e stateless por mensagem; a memoria pegajosa por
  conversa vive no `SessionDomainStore` (duravel em PostgreSQL quando
  `SESSION_DOMAIN_STORE_BACKEND=postgres`).
- o roteador apenas escolhe o dominio; toda a politica de seguranca, handoff e
  confinamento continua no `ChatFlowService` do dominio escolhido.
