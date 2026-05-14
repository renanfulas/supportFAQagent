# Como navegar no projeto

## Primeiro mapa mental

Pense no repositorio em duas partes:

- `app/`: motor compartilhado
- `domains/`: especializacao por area

Se a mudanca serve para mais de um setor, ela provavelmente mora em `app/`.
Se a mudanca so faz sentido para um setor, ela provavelmente mora em `domains/`.

## Caminho mais comum para leitura

Se voce esta chegando agora, leia nesta ordem:

1. `README.md`
2. `docs/architecture.md`
3. `docs/mvp-plan.md`
4. `docs/domain-contract.md`
5. `docs/domain-evals.md`
6. `docs/knowledge-authoring.md`
7. `docs/agent-skills.md`
8. `docs/observability.md`
9. `docs/technical-implementation-plan.md`
10. `docs/integration-contracts.md`
11. `domains/suporte-vps-whatsapp/domain.yaml`
12. `app/main.py`
13. `app/api/routes/`
14. `app/orchestration/chat_flow.py`
15. `app/retrieval/service.py`
16. `app/ingestion/service.py`

## Planos por frente

Quando a mudanca for uma frente executavel, use estes planos curtos antes de
codar:

- `docs/quality-plans/whatsapp-blocking-quality-plan.md`: qualidade de resposta para bloqueio de WhatsApp.
- `docs/quality-plans/provider-runtime-quality-plan.md`: provider real, fallback e erros observaveis.
- `docs/quality-plans/ingestion-chunking-quality-plan.md`: ingestao, chunking e preview.
- `docs/quality-plans/vector-retrieval-quality-plan.md`: embeddings, adapter vetorial e isolamento por dominio.
- `docs/quality-plans/chat-handoff-quality-plan.md`: prompt, confidence e escalonamento.
- `docs/quality-plans/feedback-n8n-quality-plan.md`: feedback, contratos n8n e preservacao de `request_id`.
- `docs/quality-plans/chat-ui-quality-plan.md`: UI local de chat, renderizacao segura e debug.

## O que procurar em cada pasta

## `app/main.py`

Mostra como a API sobe e quais rotas estao expostas.

## `app/api/routes/`

Aqui ficam os endpoints. E o lugar certo para entender o contrato publico da aplicacao.

## `app/core/request_context.py`

Centraliza o `X-Request-ID` usado para correlacionar chamadas, erros e logs.

## `app/api/schemas/`

Define entrada e saida da API.

## `app/domain_engine/`

Mostra como um dominio e carregado do disco para a aplicacao. O contrato esperado esta em `docs/domain-contract.md`.

## `app/ingestion/`

Mostra como artigos e FAQs viram insumos utilizaveis pelo RAG.

## `app/retrieval/`

Mostra como o contexto e localizado para responder perguntas.

## `app/llm/`

Mostra como os providers sao isolados do restante do sistema.

## `app/orchestration/`

Aqui esta o fluxo principal do agente. Quando quiser entender a jornada ponta a ponta, comece por aqui.

## `app/evals/`

Ferramentas locais para rodar calibragem de dominio contra casos reais versionados.

## `.agents/skills/`

Instrucoes universais para agentes de IA navegarem, decidirem proximos passos, alterarem, testarem, commitarem e abrirem PRs neste projeto.

## `domains/suporte-vps-whatsapp/`

Mostra como um dominio e definido hoje. Use essa pasta como referencia para criar novos dominios.

## `domains/suporte-vps-whatsapp/knowledge/`

Base de conhecimento do dominio inicial. Use `docs/knowledge-authoring.md` antes de adicionar ou revisar artigos.

## Como pensar uma nova mudanca

Pergunte primeiro:

1. Isso e compartilhado entre dominios ou especifico de um?
2. Isso e regra de negocio, infraestrutura ou contrato HTTP?
3. Isso muda conteudo, comportamento ou persistencia?

Esse filtro simples costuma apontar a pasta correta antes mesmo de codar.
