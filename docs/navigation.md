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
5. `docs/technical-implementation-plan.md`
6. `docs/integration-contracts.md`
7. `domains/suporte-vps-whatsapp/domain.yaml`
8. `app/main.py`
9. `app/api/routes/`
10. `app/orchestration/chat_flow.py`
11. `app/retrieval/service.py`
12. `app/ingestion/service.py`

## O que procurar em cada pasta

## `app/main.py`

Mostra como a API sobe e quais rotas estao expostas.

## `app/api/routes/`

Aqui ficam os endpoints. E o lugar certo para entender o contrato publico da aplicacao.

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

## `domains/suporte-vps-whatsapp/`

Mostra como um dominio e definido hoje. Use essa pasta como referencia para criar novos dominios.

## Como pensar uma nova mudanca

Pergunte primeiro:

1. Isso e compartilhado entre dominios ou especifico de um?
2. Isso e regra de negocio, infraestrutura ou contrato HTTP?
3. Isso muda conteudo, comportamento ou persistencia?

Esse filtro simples costuma apontar a pasta correta antes mesmo de codar.
