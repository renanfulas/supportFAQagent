# Plano De Evolucao Do Chat Web

Este documento define o plano tecnico para evoluir a interface web do
`supportFAQagent` de uma experiencia V0 estilo ChatGPT ate um fluxo
omnichannel com WhatsApp, identidade verificada, historico e operacao humana.

O objetivo e entregar valor rapido sem quebrar as promessas centrais do
produto: seguranca, rastreabilidade, respostas baseadas em conhecimento
versionado e escalonamento humano quando faltar contexto.

## Decisao Principal

A decisao aprovada para a proxima frente e:

```text
V0: Chat web estilo ChatGPT agora.
V1: Autenticacao por WhatsApp depois.
V2: Omnichannel real com historico e handoff operacional.
V3: Operacao madura com dashboard, qualidade e expansao multi-dominio.
```

Detalhamento de implementacao da primeira fase:

- [Plano De Implementacao V0 Do Chat Web](web-chat-v0-implementation-plan.md)

O ponto mais importante:

- `POST /chat` continua protegido por `X-API-Key` para integracoes internas,
  `n8n`, WhatsApp e consumidores servidor-servidor.
- O browser nao deve receber `API_SECRET_KEY`, `OPENAI_API_KEY`,
  `X-LLM-API-Key` ou qualquer segredo.
- A interface publica deve chamar uma fachada web controlada pelo backend,
  nao o contrato interno protegido diretamente.

Analogia simples:

O `X-API-Key` e a chave da loja. A UI publica e a porta da frente. Nao se cola
a chave na porta; cria-se um balcao seguro onde o cliente pede ajuda e o
sistema interno usa a chave sem expo-la.

## Estado Atual

O projeto ja possui:

- API FastAPI.
- `POST /chat` protegido.
- `POST /feedback` protegido.
- `X-Request-ID` em respostas.
- `request_id`, `references`, `confidence`, `escalated`,
  `handoff_reasons` e `error_code` no contrato de chat.
- UI local em `app/static/chat`.
- Handoff estruturado.
- Rate limit no `/chat`.
- Retrieval lexical seguro por padrao e `pgvector` disponivel por feature flag.

Limites atuais importantes:

- Persistencia real de conversas ainda esta no roadmap.
- `/feedback` ainda retorna `pending_persistence`.
- Historico curto no core esta preparado como contrato, mas ainda nao possui
  armazenamento real de conversas.
- WhatsApp e `n8n` devem continuar como consumidores de contrato, nao como
  nucleo de inteligencia.

## Objetivos Do Produto

O usuario alvo inicial e um cliente HostGator que assina VPS ou produto
relacionado e quer suporte para duvidas tecnicas.

O fluxo desejado e:

1. Cliente abre o website.
2. A tela ja abre em um chat simples, familiar e direto.
3. Cliente faz uma pergunta sobre VPS, WhatsApp ou automacoes.
4. O agente responde com base em conhecimento controlado.
5. Se faltar contexto, houver baixa confianca ou tema sensivel, o sistema
   sinaliza escalonamento humano.
6. Cliente consegue avaliar se a resposta ajudou.
7. No futuro, o mesmo cliente pode continuar pelo WhatsApp.

## Nao Objetivos

Nao fazer no V0:

- Login por WhatsApp.
- Historico persistente entre web e WhatsApp.
- Dashboard operacional completo.
- Gestao de usuarios.
- Exposicao publica de `confidence` como porcentagem de verdade.
- Uso de segredo real no JavaScript.
- Permitir que o browser escolha qualquer dominio livremente.
- Mover regra de inteligencia para o frontend ou para `n8n`.

## Arquitetura Alvo Por Fase

### V0 - Chat Web Publico Controlado

Objetivo:

Entregar uma experiencia web estilo ChatGPT, segura e rastreavel, sem login
real e sem expor segredos no navegador.

Fluxo alvo:

```text
Browser
  -> POST /web/chat
  -> fachada web publica controlada
  -> ChatFlowService
  -> retrieval + LLM + handoff
  -> resposta segura para UI
```

Contratos internos preservados:

```text
n8n / WhatsApp / automacoes
  -> POST /chat com X-API-Key
  -> mesmo core de orquestracao
```

Entregas tecnicas:

- Criar uma rota web publica controlada, por exemplo `POST /web/chat`.
- Criar uma rota web publica controlada para feedback, por exemplo
  `POST /web/feedback`.
- Manter `POST /chat` e `POST /feedback` protegidos por `X-API-Key`.
- Gerar sessao anonima web com identificador nao reversivel.
- Usar cookie `HttpOnly`, `SameSite=Lax` e `Secure` em producao quando houver
  sessao persistida no browser.
- Gerar `session_id` no formato `web:<uuid>` ou equivalente.
- Aplicar rate limit separado para a fachada web.
- Travar dominio inicial em `suporte-vps-whatsapp`.
- Retornar erro seguro com `request_id` quando algo falhar.
- Permitir feedback simples: util, nao util, motivo opcional e comentario
  curto.
- Atualizar a UI em `app/static/chat` para remover campo de API key no modo
  publico.
- Manter modo controlado de staging somente se explicitamente habilitado por
  configuracao.

Experiencia de UI:

- Abrir direto no chat.
- Ter layout inspirado em ChatGPT ou Claude: conversa central, composer fixo e
  estado de carregamento claro.
- Exibir resposta em linguagem simples.
- Exibir aviso amigavel quando houver escalonamento humano.
- Exibir referencias de forma discreta e compreensivel.
- Exibir `request_id` como codigo copiavel para suporte, nao como debug
  tecnico principal.
- Coletar feedback com botoes simples.
- Tratar erro de forma segura: "Nao consegui responder agora. Codigo de
  suporte: <request_id>."

Seguranca minima:

- Nenhum segredo no HTML, CSS, JS ou resposta publica.
- Nenhum prompt completo, telefone, API key ou payload sensivel em log.
- Rate limit por IP e por sessao.
- Limite de tamanho de mensagem preservado.
- CORS restrito quando exposto fora do mesmo dominio.
- Mensagens de erro sem stack trace.

Criterios de aceite:

- Usuario abre a UI e conversa sem preencher chave.
- `/chat` continua retornando `403` sem `X-API-Key`.
- `/web/chat` nao aceita nem exige segredo no browser.
- A resposta preserva `request_id`, `references`, `escalated`,
  `handoff_reasons` e `error_code` internamente.
- Feedback pode ser enviado sem expor segredo.
- Rate limit bloqueia abuso basico.
- `python -m compileall app tests scripts` passa.
- `python -m pytest` passa.

### V1 - Identidade Por WhatsApp

Objetivo:

Adicionar login simples por telefone com verificacao via WhatsApp, sem
transformar telefone em prova de titularidade da conta HostGator.

Fluxo alvo:

```text
Usuario informa telefone
  -> backend cria desafio OTP
  -> WhatsApp envia codigo
  -> usuario confirma codigo no site
  -> sessao web anonima vira sessao identificada
```

Entregas tecnicas:

- Criar contrato para iniciar verificacao de telefone.
- Normalizar telefone para formato E.164.
- Criar desafio OTP com codigo, expiracao, tentativas restantes e status.
- Enviar codigo via WhatsApp por integracao externa controlada.
- Confirmar codigo no backend.
- Vincular sessao web anonima ao telefone verificado.
- Iniciar persistencia de conversas e mensagens se a frente de banco estiver
  pronta.
- Manter `session_id` tratado como dado sensivel.
- Criar protecoes contra abuso: cooldown, limite por IP, limite por telefone e
  bloqueio temporario por excesso de tentativas.

Modelo conceitual minimo:

```text
web_sessions
  id
  anonymous_session_id
  verified_identity_id
  created_at
  last_seen_at

verified_identities
  id
  phone_hash
  phone_last4
  verified_at
  status

otp_challenges
  id
  identity_candidate_hash
  code_hash
  expires_at
  attempts_remaining
  status
```

Observacao:

O telefone deve ser tratado como identificador de canal, nao como garantia de
que o usuario e dono de uma conta HostGator. Se no futuro houver integracao com
conta real do cliente, isso deve entrar como um passo separado de verificacao.

Criterios de aceite:

- Usuario consegue verificar telefone por WhatsApp.
- Codigo expira.
- Tentativas sao limitadas.
- Telefone bruto nao aparece em logs.
- Sessao web verificada continua funcionando sem pedir codigo a cada mensagem.
- O sistema ainda permite conversa anonima quando o produto decidir manter essa
  entrada.

### V2 - Omnichannel Real

Objetivo:

Permitir continuidade entre website, WhatsApp e suporte humano usando a mesma
identidade e o mesmo historico operacional.

Fluxo alvo:

```text
Website chat
  -> conversation_id
  -> messages

WhatsApp webhook
  -> resolve telefone verificado
  -> mesma conversation_id ou nova conversa vinculada
  -> messages

Handoff humano
  -> ve contexto, referencias, confianca e motivos
  -> responde ou assume atendimento
```

Entregas tecnicas:

- Persistir conversas.
- Persistir mensagens.
- Registrar canal da mensagem: `web`, `whatsapp`, `human`, `system`.
- Registrar status da conversa: `bot`, `handoff_pending`, `human_active`,
  `resolved`, `closed`.
- Preservar `request_id`, `references`, `confidence`, `handoff_reasons` e
  `error_code` em cada resposta do agente.
- Criar contrato de webhook WhatsApp consumindo o mesmo core.
- Preservar `X-Request-ID` entre WhatsApp, backend e feedback.
- Criar payload de handoff para humano.
- Permitir que o atendimento humano veja ultimas mensagens e fontes usadas.

Modelo conceitual minimo:

```text
conversations
  id
  domain_id
  identity_id
  channel_origin
  status
  created_at
  updated_at

messages
  id
  conversation_id
  role
  channel
  content
  request_id
  confidence
  escalated
  handoff_reasons
  references
  error_code
  created_at
```

Regras importantes:

- `n8n` continua como consumidor e automacao externa.
- O backend continua sendo o nucleo de inteligencia.
- O WhatsApp nao deve conter regra propria para decidir resposta tecnica.
- Handoff deve usar `handoff_reasons`, nao inferir pelo texto livre.

Criterios de aceite:

- Usuario pode comecar no site e continuar pelo WhatsApp.
- Usuario pode comecar pelo WhatsApp e ter contexto visivel no suporte web.
- Escalonamento humano tem fila ou destino operacional claro.
- Feedback pode ser associado a mensagem ou resposta especifica.
- Logs preservam rastreabilidade sem vazar PII.

### V3 - Operacao Madura E Expansao

Objetivo:

Transformar o chat em uma plataforma operacional para suporte multi-dominio,
qualidade de respostas, auditoria e melhoria continua.

Entregas possiveis:

- Dashboard de conversas escaladas.
- Dashboard de feedback negativo.
- Painel de qualidade por dominio.
- Busca por `request_id`.
- Metricas de latencia, erro de provider, retrieval e handoff.
- Ferramentas para revisar referencias usadas.
- Fila de melhoria da base de conhecimento.
- Relatorio de perguntas sem resposta.
- Expansao para novos dominios alem de `suporte-vps-whatsapp`.
- Perfis de usuario: operador, supervisor, admin.
- Integracao com conta real HostGator, se houver contrato de identidade
  aprovado.

Principio:

V3 so deve entrar depois que V0, V1 e V2 tiverem contratos estaveis. Dashboard
sem persistencia confiavel vira painel bonito com dados fracos.

## Contratos Propostos

### `POST /web/chat`

Uso:

Endpoint publico controlado para o website.

Entrada minima:

```json
{
  "message": "Como conectar o WhatsApp na Evolution API?"
}
```

Regras:

- `domain` nao deve ser livre no V0.
- `session_id` deve ser resolvido pelo backend.
- Campos extras devem ser rejeitados.
- Mensagem segue o limite atual de 4000 caracteres.

Saida sugerida:

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

Observacao:

`confidence` pode continuar existindo internamente. Para o usuario final, evitar
mostrar como numero bruto no V0. Se for exibido, preferir uma camada semantica:
`alta confianca`, `precisa de humano` ou `contexto insuficiente`.

### `POST /web/feedback`

Uso:

Endpoint publico controlado para feedback da resposta no website.

Entrada minima:

```json
{
  "request_id": "uuid-retornado-pelo-chat",
  "helpful": true,
  "reason": "resolved",
  "comment": "Ajudou a resolver"
}
```

Regras:

- `session_id` deve ser resolvido pelo backend.
- `source` deve ser definido como `web`.
- Comentario deve ter limite curto.
- Feedback nao deve exigir login no V0.

## Riscos E Mitigacoes

## Segredo No Frontend

Risco:

Expor `API_SECRET_KEY` ou chave de provider no browser permite abuso direto do
backend.

Mitigacao:

- Criar fachada web publica controlada.
- Manter `/chat` protegido.
- Nunca inserir segredo em HTML, JS, localStorage ou resposta publica.

## Custo De LLM Sem Controle

Risco:

Chat publico sem limite pode gerar custo alto ou abuso automatizado.

Mitigacao:

- Rate limit por IP e sessao.
- Limite de tamanho de mensagem.
- Bloqueio progressivo.
- Observabilidade por `request_id`, erro e latencia.

## WhatsApp Auth Como Falsa Prova De Conta

Risco:

Verificar telefone prova posse do numero, nao titularidade HostGator.

Mitigacao:

- Documentar a diferenca.
- Tratar telefone como identidade de canal.
- Integrar conta real apenas em fase posterior com contrato especifico.

## Omnichannel Sem Persistencia

Risco:

Prometer continuidade entre web e WhatsApp sem `conversations` e `messages`
gera experiencia quebrada.

Mitigacao:

- V0 sem promessa de continuidade.
- V1 prepara identidade.
- V2 implementa historico real.

## Handoff Sem Destino Humano

Risco:

O sistema marca escalonamento, mas ninguem recebe.

Mitigacao:

- No V0, comunicar escalonamento de forma honesta.
- No V2, criar fila, webhook ou notificacao operacional.
- Sempre preservar `handoff_reasons`.

## Debug Exposto Ao Cliente

Risco:

Mostrar dados tecnicos demais pode confundir usuario ou revelar detalhes
operacionais.

Mitigacao:

- Mostrar `request_id` como codigo de suporte.
- Mostrar referencias de forma amigavel.
- Guardar detalhes ricos para logs e paineis internos.

## Ordem Recomendada De Implementacao

1. Criar contrato e testes de `/web/chat`.
2. Implementar resolucao de sessao anonima.
3. Implementar rate limit especifico da web.
4. Conectar `/web/chat` ao mesmo core do `/chat`.
5. Criar `/web/feedback`.
6. Atualizar UI para modo publico sem campo de chave.
7. Ajustar mensagens de erro e handoff.
8. Validar seguranca: sem segredo no browser.
9. Rodar compileall e pytest.
10. Documentar flags de ambiente e modo de deploy.

## Arquivos Provaveis

- `app/main.py`
- `app/api/routes/web_chat.py`
- `app/api/schemas/chat.py`
- `app/api/schemas/feedback.py`
- `app/core/config.py`
- `app/core/rate_limit.py`
- `app/static/chat/index.html`
- `app/static/chat/app.js`
- `app/static/chat/styles.css`
- `tests/`
- `docs/integration-contracts.md`
- `docs/observability.md`

## Validacao

Validacoes minimas para V0:

```powershell
python -m compileall app tests scripts
python -m pytest
```

Validacoes de seguranca:

- Confirmar que `/chat` retorna `403` sem `X-API-Key`.
- Confirmar que `/web/chat` nao exige segredo do browser.
- Confirmar que HTML e JS nao contem `API_SECRET_KEY`, `OPENAI_API_KEY` ou
  valores reais de segredo.
- Confirmar que erros retornam `request_id`.
- Confirmar que logs nao registram mensagem completa com PII, telefone bruto ou
  segredo.

## Prompt De Execucao Para Agente

```text
Voce e um engenheiro full-stack senior no projeto supportFAQagent.

Missao:
Implementar o V0 de uma interface web estilo ChatGPT para suporte HostGator,
sem expor API_SECRET_KEY no navegador e sem implementar WhatsApp auth ainda.

Contexto:
O backend ja possui POST /chat protegido por X-API-Key, POST /feedback
protegido, ChatFlowService, handoff estruturado, request_id, references,
confidence e uma UI estatica local em app/static/chat.

Decisoes obrigatorias:
- Manter /chat protegido para integracoes internas.
- Criar uma fachada web publica controlada para o website.
- Nao colocar API_SECRET_KEY, OPENAI_API_KEY ou X-LLM-API-Key no frontend.
- V0 usa sessao anonima web.
- V1 WhatsApp auth fica fora do escopo.
- Preservar request_id, references, confidence, escalated, handoff_reasons e
  error_code.
- Nao mover inteligencia para o frontend.

Entregaveis:
1. Proposta de arquitetura curta.
2. Lista de arquivos a alterar.
3. Implementacao incremental.
4. Testes de contrato e seguranca.
5. Validacao com compileall e pytest.

Criterio de sucesso:
O usuario consegue abrir a UI, enviar mensagem, receber resposta rastreavel,
enviar feedback e nunca expor segredos no navegador.
```
