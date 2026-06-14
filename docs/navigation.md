# Como navegar no projeto

## Primeiro mapa mental

Pense no repositorio em duas partes:

- `app/`: motor compartilhado
- `domains/`: especializacao por area

Se a mudanca serve para mais de um setor, ela provavelmente mora em `app/`.
Se a mudanca so faz sentido para um setor, ela provavelmente mora em `domains/`.

Antes de escrever texto publico, README, descricao de PR ou material para agentes, leia tambem `docs/product-positioning.md`. O projeto deve soar como produto tecnico operacional: util, rastreavel e seguro, sem prometer autonomia total.

## Caminho mais comum para leitura

Se voce esta chegando agora, leia nesta ordem:

1. `README.md`
2. `docs/product-positioning.md`
3. `docs/architecture.md`
4. `docs/documentation-status.md`
5. `docs/mvp-plan.md`
6. `docs/domain-contract.md`
7. `docs/domain-evals.md`
8. `docs/knowledge-authoring.md`
9. `docs/agent-skills.md`
10. `docs/observability.md`
11. `docs/technical-implementation-plan.md`
12. `docs/integration-contracts.md`
13. `domains/suporte-vps-whatsapp/domain.yaml`
14. `app/main.py`
15. `app/api/routes/`
16. `app/orchestration/chat_flow.py`
17. `app/retrieval/service.py`
18. `app/ingestion/service.py`
19. `app/ingestion/github_loader.py`
20. `scripts/`

## Planos por frente

Quando a mudanca for uma frente executavel ainda em aberto, use estes planos
curtos antes de codar:

- `docs/web-chat-v1-whatsapp-otp-spec.md`: contrato, threat model e fronteiras
  da identidade de canal por WhatsApp OTP.
- `docs/quality-plans/web-chat-v1b-postgres-n8n-plan.md`: evolucao persistente
  do OTP, adapter interno n8n, workflow Evolution API e smoke privado real.

Frentes ja incorporadas na `main`, como bloqueio de WhatsApp, provider/runtime,
ingestao/chunking, chat UI local, calibragem de chat/handoff e contrato de
feedback/n8n, devem ser entendidas pelo estado atual do codigo e pelos docs
principais, nao por planos de execucao antigos.

Planos concluidos, relatorios substituidos e roadmaps historicos ficam em
`docs/archive/`. Consulte `docs/archive/README.md` para localizar o substituto
ativo antes de usar qualquer documento arquivado.

## O que procurar em cada pasta

## `app/main.py`

Mostra como a API sobe e quais rotas estao expostas.

## `app/api/routes/`

Aqui ficam os endpoints. E o lugar certo para entender o contrato publico da aplicacao.

## `app/core/request_context.py`

Centraliza o `X-Request-ID` usado para correlacionar chamadas, erros e logs.

## `app/core/config.py`

Mostra variaveis de ambiente, defaults locais, feature flags como `RETRIEVAL_BACKEND` e protecoes como `API_SECRET_KEY`.

## `app/api/schemas/`

Define entrada e saida da API.

## `app/domain_engine/`

Mostra como um dominio e carregado do disco para a aplicacao. O contrato esperado esta em `docs/domain-contract.md`.

## `app/ingestion/`

Mostra como artigos e FAQs viram insumos utilizaveis pelo RAG.

Inclui tambem `github_loader.py`, que busca arquivos pela GitHub Contents API oficial. Use esse caminho para fontes GitHub; nao crie scraping de HTML do GitHub.

## `app/retrieval/`

Mostra como o contexto e localizado para responder perguntas.

## `app/llm/`

Mostra como os providers sao isolados do restante do sistema.

## `app/orchestration/`

Aqui esta o fluxo principal do agente. Quando quiser entender a jornada ponta a ponta, comece por aqui.

## `app/handoff/`

Concentra regras de escalonamento humano reutilizaveis, como baixa confianca, pedido explicito e termos sensiveis.

## `app/feedback/`

Concentra o servico e o contrato interno de feedback. Quando
`PERSISTENCE_BACKEND=postgres`, o contexto confiavel vem da resposta original
persistida e o cliente nao pode substituir referencias ou motivos de handoff.

## `app/conversations/`

Concentra persistencia sanitizada de conversas e mensagens, isolamento por
dominio, canal e hash de sessao, alem da leitura do historico curto real.

## `app/health/`

Concentra readiness operacional separado para banco, migrations, retrieval e
outbox. `GET /health` continua sendo liveness simples; `GET /health/ready` e o
gate autenticado para promover runtime.

## `app/evals/`

Ferramentas locais para rodar calibragem de dominio contra casos reais versionados.

## `app/db/` e `migrations/`

Guardam modelos, conexao e artefatos SQL. Mudancas de schema, indices, migrations e queries finais de pgvector devem respeitar ownership de banco.

O fluxo atual usa migrations SQL forward-only com ledger, checksum e runner em
`python -m scripts.migrate`. Nunca aplique `006` e `007` juntas em banco
existente sem executar o backfill e confirmar que writers legados foram
drenados.

## `app/static/`

Chat UI local/staging para validacao controlada. Nao substitui integracoes externas como WhatsApp ou n8n.

## `scripts/`

Comandos operacionais e validacoes pontuais, incluindo ingestao pgvector, preflight de runtime, smoke de staging e fetch de documento GitHub.

## `docs/security/`, `docs/runbooks/` e `docs/quality-plans/`

Guardam hardening, operacao, ambientes, checks de qualidade e planos por frente. Use esses diretorios antes de mexer em seguranca, staging, VPS, pgvector ou criterios de qualidade.

## `.agents/skills/`

Instrucoes versionadas para agentes de IA navegarem, decidirem proximos passos, alterarem, testarem, commitarem e abrirem PRs neste projeto.

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
