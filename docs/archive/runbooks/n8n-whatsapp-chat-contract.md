# Runbook - Contrato n8n/WhatsApp para `/chat`

Status: ARQUIVADO. `n8n` foi removido do projeto e os templates em
`deploy/n8n/workflows/` foram excluidos do repo. O contrato protegido `/chat`
continua valido para consumidores servidor-servidor, mas isso esta documentado
de forma atual em `../../integration-contracts.md`. Use este runbook apenas como
registro historico. Para a direcao atual de WhatsApp, use Meta WhatsApp Cloud
API nativa e o runbook `../../runbooks/meta-whatsapp-private-smoke.md`.

## Objetivo

Definir como uma automacao externa, como n8n ou WhatsApp, deve consumir o
backend sem mover inteligencia, ranking, seguranca ou regras de dominio para o
workflow.

Este runbook define o contrato da integracao. Os templates n8n versionados
ficam em `deploy/n8n/workflows/` e sua ativacao segura esta documentada em
`docs/runbooks/n8n-versioned-workflows.md`. Eles nao substituem a calibragem
do `pgvector`.

## Coexistencia Docker com a API

O `supportFAQagent` e o `n8n` podem rodar ao mesmo tempo em Docker na mesma VPS,
desde que continuem como servicos separados.

Modelo recomendado:

- `supportfaq_api`: backend Python/FastAPI do agente.
- `supportfaq_postgres`: PostgreSQL/pgvector oficial do agente.
- `n8n`: automacao externa que consome a API HTTP.
- Evolution API: servico externo de WhatsApp, com banco proprio separado.

Para subir o container do `n8n` na VPS, use
`docs/runbooks/n8n-vps-docker-deploy.md`. Esse runbook mantem o `n8n` em
Docker separado, com PostgreSQL proprio e porta exposta apenas em loopback.

Regras:

- o `n8n` deve chamar `supportfaq_api` por HTTP usando `/chat` e `/feedback`;
- o `n8n` nao deve acessar diretamente as tabelas internas do RAG;
- o `n8n` nao deve montar prompt, ranking ou contexto vetorial;
- cada servico deve ter nome, portas, volumes e variaveis proprias;
- nao subir duas instancias da API apontando para a mesma porta publica sem
  decisao explicita;
- manter rollback simples: parar/desabilitar `n8n` nao deve parar a API, e
  parar/desabilitar a API nao deve apagar banco, volumes ou workflows.

Desabilitacao temporaria esperada:

```bash
docker stop n8n
```

ou, se o `n8n` for criado como servico Swarm/EasyPanel, pausar/remover apenas o
servico `n8n`, preservando o volume de dados.

Antes de desabilitar qualquer servico, registrar:

- nome do container/servico;
- imagem usada;
- volumes associados;
- variaveis obrigatorias sem valores secretos;
- motivo da pausa;
- plano para religar.

## Chamada para `/chat`

Endpoint:

```http
POST /chat
```

Headers obrigatorios:

```http
Content-Type: application/json
X-API-Key: <api-secret-privado>
X-Request-ID: <id-unico-e-estavel-da-mensagem>
```

Payload minimo:

```json
{
  "domain": "suporte-vps-whatsapp",
  "channel": "whatsapp",
  "session_id": "whatsapp:<identificador-sanitizado-ou-interno>",
  "message": "Mensagem do usuario"
}
```

Regras:

- `domain` deve ser enviado quando a automacao souber o dominio.
- `channel` deve ser `whatsapp` para isolar corretamente o historico.
- `session_id` deve ser tratado como sensivel fora da API.
- `X-Request-ID` deve ser unico por mensagem recebida; reutilizar o mesmo valor
  para uma conversa inteira torna auditoria e feedback ambiguos.
- `message` deve ser texto puro, sem anexos, arquivos, imagens ou metadados.
- O workflow nao deve enviar senhas, tokens, headers privados ou logs crus como
  parte da mensagem.

## Campos da resposta que o n8n deve preservar

Preservar em memoria operacional, log sanitizado ou persistencia operacional:

- `request_id`
- `domain`
- `confidence`
- `escalated`
- `handoff_reasons`
- `references`
- `error_code`
- `handoff_status`
- `persistence_status`

O texto em `answer` e para o usuario final. Nao use o texto como unica fonte
para decidir roteamento quando `escalated` e `handoff_reasons` ja existem.

## Roteamento recomendado

- Se `error_code` nao for `null`, tratar como falha tecnica observavel.
- Se `escalated=true`, preservar os motivos e o status, mas nao criar uma
  segunda notificacao no workflow de entrada; a outbox do backend e o caminho
  autoritativo para `escalation-notify`.
- `handoff_status=handoff_queued` confirma que a notificacao entrou na outbox.
- `handoff_status=handoff_unavailable` significa que o workflow nao deve
  afirmar que uma pessoa foi notificada.
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
- `/health/ready` responde `200` com `X-API-Key` antes de ativar o canal
- `/domains` responde `200` apenas com `X-API-Key` valida
- `/chat` responde `200` com `request_id`
- `X-Request-ID` enviado aparece no header e no corpo
- `references` e `handoff_reasons` sao arrays
- `error_code` e preservado
- se `escalated=true`, a resposta preserva `handoff_status` e a notificacao
  humana ocorre uma unica vez pelo caminho outbox + `escalation-notify`

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
