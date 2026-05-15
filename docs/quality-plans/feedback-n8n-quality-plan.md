# Plano tecnico - Qualidade de feedback e integracao n8n

## Objetivo

Alinhar feedback, chat, observabilidade, auth e fronteiras de n8n para que
integracoes externas consumam o backend por contratos estaveis, sem mover
inteligencia, handoff, regras de prompt ou persistencia final para fora do core
Python.

Esta frente e de contrato, qualidade e operacao. O endpoint `POST /feedback`
ja aceita feedback, registra evento observavel e retorna
`storage="pending_persistence"` ate a frente de banco conectar a persistencia
real.

## Estado atual confirmado

- `POST /chat` e protegido por `X-API-Key` e retorna `request_id`, `domain`,
  `answer`, `confidence`, `escalated`, `handoff_reasons`, `references` e
  `error_code`.
- `POST /feedback` e protegido por `X-API-Key`, exige `helpful` e aceita
  `request_id`, `session_id`, `message_id`, `reason`, `comment` e `source`.
- `POST /feedback` tambem aceita, de forma opcional e compativel,
  `escalated`, `handoff_reasons`, `references` e `error_code` para preservar o
  contexto operacional da resposta avaliada.
- Campos opcionais de feedback com branco puro viram `null`; `source` tem
  default `api`, e branco puro e rejeitado.
- `comment` tem limite de 1000 caracteres; `source` tem limite de 60;
  `request_id` e `message_id` tem limite de 80; `session_id` tem limite de
  160; `reason` tem limite de 120.
- `FeedbackService` retorna `feedback_id`, `accepted=true`,
  `status="accepted"` e `storage="pending_persistence"`.
- `feedback_recorded` loga `request_id`, `chat_request_id`,
  `session_id_hash`, `helpful`, `reason`, `source` e `storage`, sem logar
  `session_id` bruto nem comentario livre.
- Todas as respostas HTTP retornam `X-Request-ID`; valores ausentes, vazios ou
  maiores que 80 caracteres sao substituidos por UUID novo.
- Erros tratados tambem retornam `request_id` no corpo e no header.

## Fronteiras de responsabilidade

O backend Python deve continuar sendo a fonte de verdade para:

- validacao de payload e auth;
- escolha de dominio;
- retrieval, prompt, LLM e fallback;
- calculo de `confidence`;
- decisao `escalated`;
- lista estruturada `handoff_reasons`;
- shape de `references`;
- codigos observaveis em `error_code`.

O n8n deve ficar limitado a:

- receber mensagem do canal externo;
- chamar `POST /chat` com headers corretos;
- preservar `X-Request-ID` e `request_id`;
- rotear para humano quando `escalated=true`;
- usar `handoff_reasons` para classificacao operacional;
- enviar `POST /feedback` com o `request_id` da resposta avaliada;
- fazer retry/backoff em falhas transientes, sem inventar resposta.

A frente de banco continua dona de schema SQL, migrations, indices,
persistencia real, queries pgvector e timestamps definitivos. Este plano nao
define tabela final nem obriga a rota atual a conhecer o schema futuro.

## Escopo desta frente

Entram nesta frente:

- manter o contrato operacional de `/chat` consumivel por n8n;
- manter o contrato operacional de `/feedback` consumivel por n8n;
- preservar correlacao por `X-Request-ID` e `request_id`;
- documentar payload minimo de escalonamento humano;
- documentar tratamento esperado de auth, rate limit e provider failure;
- garantir que observabilidade nao exponha PII, secrets ou comentarios livres;
- preparar persistencia futura sem quebrar `pending_persistence`.

Ficam fora desta frente:

- criar ou versionar workflow n8n completo;
- colocar API key em workflow, README, plano ou exemplo versionado real;
- persistir feedback em PostgreSQL antes do schema estar pronto;
- definir migrations, indices ou tabelas finais;
- mandar mensagens reais de WhatsApp;
- implementar painel de atendimento humano;
- mover handoff, prompt, confidence, retrieval ou regra de negocio para n8n;
- salvar PII sem politica de retencao.

## Contrato operacional para n8n

Para chamar `POST /chat`, o consumidor externo deve:

- enviar `X-API-Key` com a chave de ambiente da integracao;
- enviar ou preservar `X-Request-ID` com ate 80 caracteres;
- enviar `domain`, `session_id` e `message` conforme contrato atual;
- tratar o canal como texto-only, sem anexos, uploads ou metadados de arquivo;
- guardar o `request_id` retornado no corpo;
- guardar `references` como `list[str]`, sem assumir metadados ricos;
- rotear para humano quando `escalated=true`;
- usar `handoff_reasons` em vez de inferir pelo texto da resposta;
- preservar `error_code` quando existir.

Para chamar `POST /feedback`, o consumidor externo deve:

- enviar `X-API-Key`;
- enviar ou preservar `X-Request-ID`;
- enviar `helpful`;
- enviar `request_id` com o valor retornado pela resposta do `/chat`, quando
  existir;
- enviar `session_id` apenas quando necessario para correlacao operacional;
- usar `message_id` somente como identificador externo opcional do canal;
- manter `source` explicito, por exemplo `n8n`, quando a origem for workflow;
- nao enviar comentario livre com token, senha, telefone desnecessario ou dado
  sensivel.

## Payload minimo de escalonamento humano

Quando `POST /chat` retornar `escalated=true`, o n8n deve montar a tarefa humana
com dados tecnicos suficientes para auditoria, mas sem duplicar inteligencia do
backend:

```json
{
  "request_id": "uuid-ou-header-retornado",
  "session_id": "identificador-do-canal",
  "domain": "suporte-vps-whatsapp",
  "answer": "texto enviado ou sugerido ao usuario",
  "confidence": 0.42,
  "handoff_reasons": ["low_confidence"],
  "references": ["domains/.../knowledge/...md"],
  "error_code": null
}
```

Regras:

- `handoff_reasons` e o campo operacional principal para triagem;
- `answer` nao deve ser usado como fonte de verdade para decidir handoff;
- `session_id` deve ser tratado como dado sensivel fora da API;
- `references` deve ser preservado como lista serializavel para auditoria;
- se `error_code` indicar falha tecnica, o fluxo humano deve receber contexto
  de erro sem expor stack trace ou segredo.

## Auth e headers

Regras atuais que a frente deve preservar:

- `POST /chat`, `POST /feedback` e `POST /ingestion/preview` exigem
  `X-API-Key`.
- Chamadas sem chave valida retornam `403` com `detail="Invalid API key"`.
- `API_SECRET_KEY` e obrigatoria fora de `development`, `dev` ou `local`.
- A chave local `local-dev-api-key` e apenas fallback de desenvolvimento.
- `X-LLM-API-Key` so existe para testes da `/chat-ui` em staging com
  `ENABLE_CHAT_UI=true`; nao deve ser usado por n8n como auth de integracao e
  nao bypassa auth em producao.
- `X-Request-ID` deve ser preservado em chamadas encadeadas quando possivel.

## Observabilidade

Eventos relevantes para esta frente:

- `http_request`: metodo, path, status e `request_id`.
- `http_error`: erro HTTP tratado com status e `request_id`.
- `validation_error`: payload invalido com `request_id`.
- `unexpected_error`: erro inesperado com status 500, tipo e `request_id`.
- `chat_completed`: dominio, `session_id_hash`, confianca, escalonamento,
  motivos e erro.
- `feedback_recorded`: feedback recebido, origem, `session_id_hash` e
  armazenamento atual.

Campos que devem ser preservados por logs, n8n e persistencia futura:

- `request_id`;
- `chat_request_id`, quando o evento for feedback;
- `domain`;
- `session_id_hash`, nao `session_id` bruto;
- `confidence`;
- `escalated`;
- `handoff_reasons`;
- `references`;
- `error_code`;
- `storage`.

Conteudo que nao deve ser logado:

- API keys, tokens, senhas ou secrets;
- `session_id` bruto quando contiver telefone, usuario externo ou canal;
- comentario livre de feedback;
- prompt completo em producao;
- stack trace bruto para usuario final.

## Falhas e retries

Tratamento esperado no consumidor externo:

- `403`: falha de autenticacao/configuracao da integracao; nao fazer retry
  automatico sem corrigir segredo.
- `422`: payload invalido; corrigir mapping do workflow antes de reenviar.
- `429`: aplicar retry com backoff e jitter, preservando correlacao.
- `5xx`: retry limitado com backoff; se persistir, abrir trilha humana ou
  alerta operacional.
- `error_code="provider_error"` ou erro tecnico equivalente no `/chat`:
  preservar o codigo, nao inventar resposta no n8n e encaminhar conforme regra
  operacional.

## Conteudo proibido

Esta frente nao deve:

- versionar API key, token de provider, senha de painel ou webhook secreto;
- logar telefone, email, token, prompt sensivel ou `session_id` bruto;
- duplicar regra de prompt, confidence, retrieval ou handoff no n8n;
- inferir escalonamento pelo texto quando `escalated` e `handoff_reasons`
  existem;
- transformar `references` em objeto rico sem versao nova de contrato;
- quebrar a resposta atual de `/feedback` sem migracao documentada;
- acoplar a rota de feedback ao schema SQL final antes da frente de banco.

## Testes de contrato a manter

Casos minimos ja alinhados ou esperados:

- `/feedback` exige `X-API-Key`.
- payload valido retorna `accepted=true`, `status="accepted"` e
  `storage="pending_persistence"`.
- `helpful` e obrigatorio.
- campos opcionais em branco viram `null` no schema.
- `source` tem default `api`, normaliza espacos e rejeita branco puro.
- comentario acima de 1000 caracteres e rejeitado.
- contrato de `ChatResponse` preserva `handoff_reasons` e `references` como
  listas de strings.
- contrato de `FeedbackResponse` permanece simples para persistencia futura.
- `X-LLM-API-Key` nao bypassa auth de producao.

## Validacao recomendada

Validacao especifica desta frente:

```powershell
python -m pytest tests/test_feedback.py tests/test_integration_contracts.py tests/test_auth.py
```

Validacao completa antes de commit quando houver mudanca de codigo:

```powershell
python -m compileall app scripts tests
python -m pytest
```

Como esta revisao e documental e limitada a este plano, a validacao principal e
comparar o conteudo com os contratos atuais de `docs/integration-contracts.md`,
`docs/observability.md`, schemas, rota e testes.

## Criterios de pronto

- n8n consegue consumir `/chat` e `/feedback` somente pelo contrato documentado.
- `X-Request-ID`, `request_id` e `chat_request_id` ficam rastreaveis.
- `handoff_reasons`, `escalated`, `references` e `error_code` sao preservados.
- Feedback continua aceito sem persistencia real e sem prometer schema final.
- Nenhuma regra central de inteligencia foi movida para automacao externa.
- Dados sensiveis sao mascarados, omitidos ou tratados como sensiveis.
- Auth de integracao fica separada do atalho de teste da `/chat-ui`.
- Testes cobrem autorizacao, validacao e shape de resposta.

## Estimativa

- Revisar contratos atuais: 30 a 60 minutos.
- Ajustar plano, exemplos e criterios de qualidade: 45 a 90 minutos.
- Validar fluxo documental contra testes e schemas: 30 a 60 minutos.

Total esperado: 1,75 a 3,5 horas.
