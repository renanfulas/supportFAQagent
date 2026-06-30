# Como navegar no projeto

## Primeiro mapa mental

Pense no repositorio em duas partes:

- `app/`: motor compartilhado
- `domains/`: especializacao por area

Se a mudanca serve para mais de um setor, ela provavelmente mora em `app/`.
Se a mudanca so faz sentido para um setor, ela provavelmente mora em `domains/`.

Antes de escrever texto publico, README, descricao de PR ou material para agentes, leia tambem `docs/product-positioning.md`. O projeto deve soar como produto tecnico operacional: util, rastreavel e seguro, sem prometer autonomia total.

## Comece Em 10 Minutos

Novos contribuidores nao precisam ler toda a documentacao. Para formar o mapa
mental minimo:

1. Leia `README.md` para entender produto e status.
2. Leia `docs/project-map.md` para ver o estado de cada frente (feito, em
   andamento, falta) e a organizacao das pastas de documentacao.
3. Leia `docs/architecture/architecture.md` para entender o fluxo e os limites.
4. Leia `CONTRIBUTING.md` para preparar e validar uma mudanca.
5. Escolha sua tarefa na tabela abaixo e leia apenas as fontes indicadas.

Este documento e o roteador por tarefa; `docs/project-map.md` e o mapa de
estado das frentes. Os dois se complementam.

## Leitura Por Tarefa

| Quero mudar | Leia primeiro | Onde trabalhar |
| --- | --- | --- |
| API ou contrato externo | `docs/architecture/integration-contracts.md` | `app/api/`, `tests/` |
| Fluxo de resposta, LLM ou handoff | `docs/architecture/domain-contract.md`, `docs/MVP/technical-implementation-plan.md` | `app/orchestration/`, `app/llm/`, `app/handoff/` |
| Artigos, FAQs ou calibragem | `docs/architecture/knowledge-authoring.md`, `docs/architecture/domain-evals.md` | `domains/`, `app/evals/` |
| Fronteira core vs dominio, seams, extensao (framework) | `docs/architecture/framework-boundary.md`, `docs/architecture/domain-contract.md`, `docs/architecture/architecture.md` | `app/`, `domains/` |
| Banco, migrations ou pgvector | `docs/MVP/technical-implementation-plan.md`, `docs/runbooks/pgvector-promotion-checklist.md` | `app/db/`, `migrations/`, `app/retrieval/` |
| Staging, VPS, Meta WhatsApp, Hermes ou operacao | `docs/setup/environments.md`, `docs/architecture/integration-contracts.md`, runbook especifico em `docs/runbooks/` | `scripts/`, configuracao de runtime |
| Seguranca ou observabilidade | `SECURITY.md`, `docs/architecture/observability.md` | `app/core/`, `app/api/`, `tests/security/` |
| Planejamento ou status do MVP | `docs/project-map.md`, `docs/documentation-status.md`, `docs/MVP/mvp-plan.md` | documentos ativos indicados por eles |
| Contribuicao com agente de IA | `docs/agent-skills.md` | `.agents/skills/` |

Se um documento estiver em `docs/archive/`, ele e contexto historico, nao uma
instrucao operacional atual.

## Planos por frente

Quando a mudanca for uma frente executavel ainda em aberto, use estes planos
curtos antes de codar:

- `docs/quality-plans/web-chat-v1-whatsapp-otp-spec.md`: contrato, threat model e fronteiras
  da identidade de canal por WhatsApp OTP.
- `docs/quality-plans/customer-identity-whatsapp-handoff-plan.md`: plano
  tecnico para ligar Auth WhatsApp, identidade do cliente, historico,
  preferencias de front end, ticket humano e notificacao WhatsApp para o time.
- `docs/quality-plans/meta-whatsapp-native-integration-plan.md`: plano tecnico
  para refatorar a entrega externa, preparar Meta WhatsApp Cloud API nativa e
  limitar Hermes a adapter temporario. `n8n` foi removido do projeto; o plano
  historico da ponte OTP n8n/Evolution esta em
  `docs/archive/implementation-plans/web-chat-v1b-postgres-n8n-plan.md`.
- `docs/quality-plans/vendas-funnel-hardening-plan.md`: plano tecnico para
  endurecer o funil de vendas no WhatsApp (dado de cartao/PAN, escopo ciente de
  contexto, separar sinal soft de fila humana, loop de descoberta), ordenado por
  risco e com pre-requisitos de instrumentacao, flag e deploy.
- `docs/runbooks/meta-whatsapp-private-smoke.md`: smoke privado sanitizado para
  validar webhook Meta e Hermes sem imprimir secrets ou payload bruto. Use
  `scripts/meta_whatsapp_activation_suite.py` para gerar preflight, smoke opt-in
  e evidencia em um diretorio unico sem enviar WhatsApp por padrao.
- `docs/runbooks/vps-capacity-and-docker-cleanup.md`: alerta de disco, politica
  de limpeza Docker/cache, protecao de volumes PostgreSQL/pgvector e evidencia
  minima de restore cronometrado isolado.
- `docs/quality-plans/conversation-persistence-tiering-plan.md`: decisao de
  arquitetura e plano em fatias para persistencia de conversa em camadas (hot
  RAM/Redis, operacional Redis+AOF, sink append-only off-box ja implementado,
  Postgres como warehouse com sumarizacao noturna) e maquina de estados de sessao.

Frentes ja incorporadas na `main`, como bloqueio de WhatsApp, provider/runtime,
ingestao/chunking, chat UI local, calibragem de chat/handoff e contrato de
feedback/outbox, devem ser entendidas pelo estado atual do codigo e pelos docs
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

Mostra como um dominio e carregado do disco para a aplicacao. O contrato esperado esta em `docs/architecture/domain-contract.md`.

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

Chat UI local/staging para validacao controlada. Nao substitui integracoes externas como Meta WhatsApp, Hermes ou outros consumidores servidor-servidor.

## `scripts/`

Comandos operacionais e validacoes pontuais, incluindo ingestao pgvector, preflight de runtime, smoke de staging e fetch de documento GitHub.

## Pastas de `docs/`

A documentacao e organizada por tipo. Use `docs/project-map.md` para o estado
das frentes e esta tabela para saber em qual pasta procurar:

| Pasta | O que vive aqui |
| --- | --- |
| `docs/` (raiz) | Indices transversais: `project-map.md`, `navigation.md`, `documentation-status.md`, `product-positioning.md`, `agent-skills.md`, `references-legacy.md` |
| `docs/architecture/` | Design, fronteiras, contratos e padroes do sistema |
| `docs/setup/` | Guias de instalacao e configuracao de ambiente |
| `docs/MVP/` | Planos tecnicos majoritarios do MVP (visao geral) |
| `docs/quality-plans/` | Planos detalhados por frente do MVP |
| `docs/runbooks/` | Procedimentos operacionais de execucao |
| `docs/security/` | Planos e contratos de seguranca |
| `docs/archive/` | Concluido, substituido ou obsoleto (contexto historico) |

## `.agents/skills/`

Instrucoes versionadas para agentes de IA navegarem, decidirem proximos passos, alterarem, testarem, commitarem e abrirem PRs neste projeto.

## `domains/suporte-vps-whatsapp/`

Mostra como um dominio e definido hoje. Use essa pasta como referencia para criar novos dominios.

## `domains/suporte-vps-whatsapp/knowledge/`

Base de conhecimento do dominio inicial. Use `docs/architecture/knowledge-authoring.md` antes de adicionar ou revisar artigos.

## Como pensar uma nova mudanca

Pergunte primeiro:

1. Isso e compartilhado entre dominios ou especifico de um?
2. Isso e regra de negocio, infraestrutura ou contrato HTTP?
3. Isso muda conteudo, comportamento ou persistencia?

Esse filtro simples costuma apontar a pasta correta antes mesmo de codar.
