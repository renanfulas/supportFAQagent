# Plano De Implementacao V0 Do Chat Web

Este documento detalha a implementacao da V0 do chat web do
`supportFAQagent`.

A V0 deve entregar uma experiencia estilo ChatGPT para o website, mas sem
autenticacao por WhatsApp, sem historico persistente e sem expor segredos no
navegador.

Documento pai:

- [Plano De Evolucao Do Chat Web](web-chat-evolution-plan.md)

## Decisao De Escopo

V0 e uma fachada publica controlada para o website.

Ela nao substitui o contrato interno atual:

- `POST /chat` continua protegido por `X-API-Key`.
- `POST /feedback` continua protegido por `X-API-Key`.
- `POST /web/chat` sera o contrato publico controlado para o browser.
- `POST /web/feedback` sera o contrato publico controlado para feedback do
  browser.

Regra de ouro:

Nenhum segredo deve atravessar o frontend. O browser nunca deve receber
`API_SECRET_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `X-API-Key` ou
`X-LLM-API-Key`.

## Objetivo Da V0

Permitir que um cliente HostGator abra uma tela de chat no website, envie uma
duvida sobre VPS, WhatsApp ou automacoes, receba uma resposta rastreavel do
agente e envie feedback simples.

## Fora Do Escopo Da V0

- Login por telefone.
- OTP por WhatsApp.
- Vinculo com conta real HostGator.
- Historico persistido.
- Continuar conversa entre web e WhatsApp.
- Dashboard interno.
- Painel humano de atendimento.
- Upload de arquivo, imagem, PDF ou anexo.
- Escolha livre de dominio pelo browser.
- Promessa de que o bot resolve tudo sem humano.

## Arquitetura Da V0

Fluxo publico:

```text
Browser
  -> POST /web/chat
  -> WebChatService ou route facade
  -> ChatFlowService
  -> retrieval + LLM + handoff
  -> resposta segura para UI
```

Fluxo interno preservado:

```text
n8n / WhatsApp / automacoes internas
  -> POST /chat com X-API-Key
  -> ChatFlowService
```

Feedback publico:

```text
Browser
  -> POST /web/feedback
  -> FeedbackService
  -> storage atual: pending_persistence
```

## Configuracao

Adicionar configuracoes em `app/core/config.py`:

```text
ENABLE_PUBLIC_CHAT_UI=false
WEB_CHAT_RATE_LIMIT_PER_MINUTE=10
WEB_CHAT_SESSION_COOKIE=sfaq_web_session
WEB_CHAT_COOKIE_SECURE=true em production
```

Comportamento recomendado:

- Em `development`, a UI local pode continuar disponivel para validacao.
- Em `production`, a UI publica so deve ser servida se
  `ENABLE_PUBLIC_CHAT_UI=true`.
- `WEB_CHAT_RATE_LIMIT_PER_MINUTE` deve ser separado de
  `RATE_LIMIT_PER_MINUTE`, porque trafego publico e trafego interno tem perfis
  diferentes.

## Sessao Anonima

V0 precisa de sessao anonima apenas para:

- gerar `session_id` estavel por navegador;
- aplicar rate limit por sessao;
- permitir feedback associado ao mesmo contexto local.

Formato interno:

```text
web:<uuid>
```

Cookie:

```text
Nome: sfaq_web_session
HttpOnly: true
SameSite: Lax
Secure: true em production
Max-Age: sugestao inicial de 7 dias
```

Regras:

- Se o cookie nao existir, criar novo UUID.
- Se o cookie for invalido, criar novo UUID.
- Nao aceitar `session_id` enviado pelo browser no payload.
- Nao logar o valor bruto da sessao.
- Logs devem usar `session_id_hash`.

Implementacao minima:

- Criar helper em `app/core/web_session.py` ou dentro da rota se for simples.
- Preferir helper separado se a logica passar de poucas linhas.

## Contrato `POST /web/chat`

Entrada:

```json
{
  "message": "Como conectar o WhatsApp na Evolution API?"
}
```

Schema sugerido:

```python
class WebChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
```

Validacoes:

- `message` obrigatorio.
- `message` nao pode ser branco puro.
- `message` deve passar pelo mesmo `sanitize_user_input`.
- Campos extras devem retornar `422`.
- `domain` nao deve ser aceito no V0.
- `session_id` nao deve ser aceito no V0.

Saida:

```json
{
  "request_id": "uuid",
  "answer": "Resposta final para o usuario.",
  "escalated": false,
  "handoff_reasons": [],
  "references": ["qrcode-whatsapp.md"],
  "support_code": "uuid",
  "error_code": null
}
```

Campos internos que podem continuar sendo calculados:

- `domain`
- `confidence`

Regra de exibicao:

- `confidence` nao precisa sair no contrato publico V0.
- Se for necessario expor depois, usar semantica de produto, nao numero cru.

Exemplo:

```json
{
  "confidence_label": "alta_confianca"
}
```

## Contrato `POST /web/feedback`

Entrada:

```json
{
  "request_id": "uuid-retornado-pelo-chat",
  "helpful": true,
  "reason": "resolved",
  "comment": "A resposta ajudou."
}
```

Schema sugerido:

```python
class WebFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(max_length=80)
    helpful: bool
    reason: str | None = Field(default=None, max_length=120)
    comment: str | None = Field(default=None, max_length=500)
```

Regras:

- `source` deve ser definido pelo backend como `web`.
- `session_id` deve vir da sessao anonima do backend.
- `handoff_reasons`, `references`, `escalated` e `error_code` podem ser
  reenviados pelo frontend somente se retornados pelo `/web/chat`, mas a V0
  pode comecar apenas com `request_id`, `helpful`, `reason` e `comment`.
- Comentario publico deve ter limite menor que o contrato interno para reduzir
  abuso.

Saida:

Pode reutilizar `FeedbackResponse`:

```json
{
  "feedback_id": "uuid",
  "accepted": true,
  "status": "accepted",
  "storage": "pending_persistence"
}
```

## Rota E Modulos

Criar:

```text
app/api/routes/web_chat.py
```

Possiveis schemas:

```text
app/api/schemas/web_chat.py
```

Ou manter em `app/api/schemas/chat.py` se o arquivo continuar pequeno.

Recomendacao:

Criar `web_chat.py` para deixar explicita a diferenca entre contrato publico
web e contrato interno protegido.

Registrar em `app/main.py`:

```python
application.include_router(web_chat.router, prefix="/web", tags=["web"])
```

Rotas esperadas:

```text
POST /web/chat
POST /web/feedback
```

## Rate Limit

Usar `InMemoryRateLimiter` na V0.

Chaves recomendadas:

```text
web:<client_ip>:chat
web-session:<session_uuid>:chat
```

Comportamento minimo:

- Limitar por IP.
- Se a sessao existir, limitar tambem por sessao.
- Retornar `429` com `Retry-After`.
- Retornar `request_id` no corpo.

Observacao:

`InMemoryRateLimiter` e aceitavel no MVP local/staging, mas nao e suficiente
para producao com multiplas replicas. Se houver deploy horizontal, migrar para
Redis ou rate limit no edge/reverse proxy.

## UI V0

Arquivos:

```text
app/static/chat/index.html
app/static/chat/app.js
app/static/chat/styles.css
```

Alteracoes obrigatorias:

- Remover campo de API key da experiencia publica.
- Alterar fetch de `/chat` para `/web/chat`.
- Alterar feedback para `/web/feedback`.
- Nao enviar `domain`.
- Nao enviar `session_id`.
- Nao enviar headers sensiveis.
- Preservar `request_id` localmente para feedback.

Estados de UI:

- Tela inicial aberta no chat.
- Mensagem do usuario.
- Estado "Gerando resposta...".
- Resposta do agente.
- Estado de erro com codigo de suporte.
- Aviso de escalonamento quando `escalated=true`.
- Referencias amigaveis.
- Botoes "Ajudou" e "Nao ajudou".

Texto recomendado para escalonamento:

```text
Talvez seja melhor um humano revisar este caso. Guarde o codigo de suporte:
<request_id>.
```

Texto recomendado para erro:

```text
Nao consegui responder agora. Tente novamente em instantes. Codigo de suporte:
<request_id>.
```

## Observabilidade

Novo evento sugerido:

```text
web_chat_completed
```

Campos:

- `request_id`
- `domain`
- `session_id_hash`
- `confidence`
- `escalated`
- `handoff_reasons`
- `error_code`
- `retrieval_backend`
- `references_count`
- `total_ms`
- `retrieval_ms`
- `llm_ms`

Feedback:

Pode reutilizar `feedback_recorded`, com `source=web`.

Dados proibidos:

- mensagem completa do usuario;
- telefone;
- segredo;
- prompt completo;
- resposta completa quando houver risco de PII;
- cookie bruto;
- session id bruto.

## Testes Obrigatorios

Criar arquivo sugerido:

```text
tests/test_web_chat.py
```

Casos minimos:

1. `POST /web/chat` aceita payload valido sem `X-API-Key`.
2. `POST /web/chat` rejeita `domain` extra com `422`.
3. `POST /web/chat` rejeita `session_id` extra com `422`.
4. `POST /web/chat` retorna cookie de sessao anonima quando ausente.
5. `POST /web/chat` reutiliza sessao quando cookie valido existe.
6. `POST /web/chat` retorna `request_id` e `support_code`.
7. `POST /web/chat` nao retorna `confidence` se essa for a decisao final da
   V0.
8. `POST /web/chat` retorna `429` quando passa do limite.
9. `POST /web/feedback` aceita feedback sem `X-API-Key`.
10. `POST /web/feedback` define `source=web`.
11. `POST /web/feedback` rejeita campo extra com `422`.
12. `/chat` continua exigindo `X-API-Key`.
13. HTML e JS nao contem `X-API-Key`, `OPENAI_API_KEY`, `API_SECRET_KEY` ou
    `X-LLM-API-Key`.

Testes existentes que devem continuar passando:

- `tests/test_auth.py`
- `tests/test_feedback.py`
- `tests/test_rate_limit.py`
- `tests/test_request_observability.py`
- `tests/test_observability_hardening.py`

## Validacao Manual

Rodar localmente:

```powershell
uvicorn app.main:app --reload
```

Abrir:

```text
http://localhost:8000/chat-ui
```

Validar:

- a tela abre sem campo de API key;
- mensagem gera resposta;
- erro mostra codigo de suporte;
- feedback funciona;
- DevTools nao mostra segredo;
- request nao envia `X-API-Key`;
- request nao envia `X-LLM-API-Key`.

## Comandos De Validacao

```powershell
python -m compileall app tests scripts
python -m pytest
```

Se mexer em comportamento do agente, handoff ou prompt:

```powershell
python -m app.evals.run_domain_eval suporte-vps-whatsapp
```

## Ordem De Implementacao Recomendada

1. Criar schemas web.
2. Criar helper de sessao anonima.
3. Criar rota `app/api/routes/web_chat.py`.
4. Conectar rota ao `ChatFlowService`.
5. Adicionar rate limit web.
6. Criar rota `POST /web/feedback`.
7. Registrar router em `app/main.py`.
8. Adicionar testes de contrato e seguranca.
9. Atualizar UI para usar `/web/chat` e `/web/feedback`.
10. Remover campo de API key da UI publica.
11. Atualizar docs de contrato, se o endpoint for confirmado.
12. Rodar validacoes.

## Riscos Que Podem Quebrar A V0

## Provider Real Ausente

Se `OPENAI_API_KEY` ou provider configurado estiver ausente, o core deve
retornar fallback seguro. A UI deve tratar isso como erro operacional ou
resposta escalada, sem expor stack trace.

## Rate Limit Apenas Em Memoria

Funciona para uma instancia. Em multiplas instancias, cada processo tera seu
proprio contador. Antes de producao com escala horizontal, mover rate limit
para camada compartilhada.

## Cookie Em HTTP Local

`Secure=true` nao funciona em `http://localhost`. A configuracao deve ser:

- `Secure=false` em `development`;
- `Secure=true` fora de desenvolvimento.

## Excesso De Debug Na UI

O cliente final deve ver suporte e clareza, nao painel tecnico. Detalhes ricos
ficam para logs e futuros dashboards internos.

## Criterio De Pronto

A V0 esta pronta quando:

- UI abre direto no chat.
- Browser conversa via `/web/chat`.
- Browser envia feedback via `/web/feedback`.
- Nenhum segredo aparece no frontend.
- `/chat` e `/feedback` internos continuam protegidos.
- Sessao anonima funciona via cookie.
- Rate limit publico funciona.
- Erros retornam `request_id`.
- Testes automatizados cobrem contrato, seguranca e regressao.
- `compileall` e `pytest` passam.
