# Arquitetura

## Visao geral

O projeto e o nucleo tecnico do `supportFAQagent`: um agente de suporte por dominio para responder duvidas recorrentes com base em conhecimento controlado, preservar rastreabilidade e escalar para humano quando o contexto nao for suficiente.

A mesma base tecnica deve suportar setores diferentes, trocando principalmente:

- artigos e FAQs
- prompts
- regras de escalonamento
- configuracao do dominio

O primeiro dominio e `suporte-vps-whatsapp`.

## Promessa operacional

A arquitetura deve proteger estas promessas:

- responder com evidencias recuperaveis
- evitar resposta inventada quando o contexto for fraco
- retornar `request_id`, `references`, `confidence`, `handoff_reasons` e `error_code`
- falhar de forma segura quando retrieval, provider ou credencial falhar
- manter Meta WhatsApp, Hermes temporario e outros canais como consumidores ou
  adapters de contrato, nao como nucleo de inteligencia

## Principios da arquitetura

- O nucleo do sistema deve ser reutilizavel entre dominios.
- O comportamento especifico de cada area deve entrar por configuracao e conteudo.
- O fluxo de atendimento deve continuar simples enquanto o MVP amadurece.
- O projeto deve poder evoluir para RAG vetorial sem reescrever a API.

## Persistencia multi-dominio

O banco do projeto deve nascer como banco da plataforma, nao como banco do
primeiro dominio.

Isso significa:

- um unico PostgreSQL oficial por ambiente
- `pgvector` no mesmo banco da aplicacao
- isolamento obrigatorio por `domain_id`
- tabelas centrais genericas para conhecimento, retrieval, conversas e mensagens
- comportamento especifico de suporte, vendas, onboarding ou atendimento fora do schema central

O que deve ficar no core:

- `domains`
- `articles`
- `article_chunks`
- `conversations`
- `messages`

O que nao deve ser hardcoded no core:

- campos especificos de VPS ou WhatsApp
- colunas especificas de vendas ou onboarding
- regras de handoff por setor
- detalhes operacionais de Meta, Hermes ou canais externos

Esses detalhes devem continuar em `domains/<domain>/`, contratos HTTP e
integracoes externas.

## Camadas

## `app/api`

Ponto de entrada HTTP com FastAPI.

Responsabilidades:

- receber requests
- validar payloads
- chamar servicos de orquestracao
- devolver respostas padronizadas

Nao deve:

- conter regra de negocio complexa
- conhecer detalhes internos de persistencia ou embeddings

## `app/core`

Infraestrutura transversal.

Responsabilidades:

- configuracao
- logging
- contexto de request com `X-Request-ID`
- utilitarios compartilhados

## `app/domain_engine`

Camada que transforma um dominio versionado em configuracao executavel.

Responsabilidades:

- listar dominios
- carregar `domain.yaml`
- padronizar configuracoes

Essa camada e a chave para manter o projeto desacoplado.

## `app/ingestion`

Leitura da base de conhecimento.

Responsabilidades:

- carregar documentos
- padronizar conteudo
- gerar chunks
- apoiar ingestao CSV de chamados quando houver fonte curada

No estado atual, os documentos locais continuam sendo a base do fluxo `/chat`. Tambem existem utilitarios novos para CSV e pipeline com LangChain, mas eles ainda precisam ser consolidados com a ingestao principal antes de virar caminho oficial de producao.

A API tambem expoe `POST /ingestion/preview`, que recebe documentos em JSON e retorna chunks para revisao. Esse contrato nao persiste dados e nao gera embeddings; ele existe para apoiar curadoria e integracoes futuras.

Quando a fonte estiver no GitHub, use `app/ingestion/github_loader.py`, que acessa a Contents API oficial e evita scraping de HTML. O script `scripts/fetch_github_document.py` existe para validacao operacional desse caminho.

## `app/retrieval`

Busca de contexto para resposta.

Responsabilidades:

- localizar trechos relevantes
- ranquear contexto
- entregar evidencias para o fluxo de chat

Hoje o fluxo `/chat` usa retrieval lexical como padrao seguro em local/CI e usa
`pgvector` como default operacional do staging por `RETRIEVAL_BACKEND=pgvector`
quando o ambiente tiver `DATABASE_URL`, embeddings e dados ingeridos. Chroma
deve continuar como adapter local/prototipo, nao como fonte oficial de
producao.

O retrieval ja passa por uma interface `VectorStore`. `LexicalVectorStore`
permanece como fallback local/rollback; `PgVectorStore` implementa o caminho
vetorial oficial do staging; `ChromaStore` implementa o mesmo contrato como
prototipo local.

## `app/llm`

Abstracao dos modelos.

Responsabilidades:

- isolar provider de LLM
- permitir mock no desenvolvimento
- facilitar troca entre OpenAI, Anthropic ou open source

O `LLMService` roteia para `LLMWrapper` com OpenAI/Anthropic quando o dominio aponta para provider real. Quando faltam credenciais ou o provider falha, o fluxo deve preservar fallback seguro e erro rastreavel.

## `app/orchestration`

Fluxo principal do agente.

Responsabilidades:

- recuperar contexto
- montar prompt
- chamar o provider
- calcular confianca
- decidir escalonamento

O `ChatFlowService` usa `prompt_builder.py` como ponto unico de montagem de
prompt. Quando `PERSISTENCE_BACKEND=postgres` e existe `session_id`, o fluxo
carrega historico curto sanitizado e isolado por dominio, canal e hash de
sessao. O historico entra no prompt como dado nao confiavel e nunca como
instrucao.

O fluxo tambem retorna `request_id` e `error_code` quando ha falha observavel de retrieval ou provider.

## `app/conversations`

Persistencia e leitura de historico curto.

Responsabilidades:

- persistir mensagens sanitizadas de usuario e agente na mesma transacao do
  audit e da outbox;
- associar turnos por `turn_id`, `request_id`, dominio, canal e hash de sessao;
- nunca persistir `session_id` bruto;
- carregar apenas mensagens verificadas pela versao de redacao atual;
- falhar aberto na leitura de historico sem derrubar o `/chat`.

## `app/handoff`

Camada de decisao de escalonamento humano.

Responsabilidades:

- escalar por baixa confianca
- escalar por pedido explicito de humano
- escalar por termos sensiveis configurados no dominio
- retornar motivos estruturados para automacoes futuras

## `app/evals`

Calibragem local por dominio.

Responsabilidades:

- carregar suites de eval versionadas no dominio
- executar perguntas reais contra o fluxo atual
- comparar escalonamento, referencias, termos esperados e motivos de handoff
- servir como linha de base antes de mudar retrieval, prompt ou provider

## `domains/`

Camada de especializacao por setor.

Cada dominio deve concentrar:

- `domain.yaml`
- prompts
- artigos
- FAQs
- evals locais

Com isso, um novo setor deve exigir pouco codigo novo e muita configuracao boa.

Exemplos esperados de dominios futuros:

- suporte tecnico
- vendas
- onboarding
- atendimento operacional

## Fluxo atual do MVP

1. A API recebe uma pergunta.
2. O sistema resolve o dominio informado ou usa o padrao.
3. O `domain_engine` carrega regras e fontes de conhecimento.
4. O `ingestion` le os documentos e gera chunks.
5. O `retrieval` busca os trechos mais proximos da pergunta.
6. O `orchestration` monta o prompt com contexto.
7. O `llm` tenta gerar a resposta pelo provider configurado.
8. O sistema calcula confianca.
9. Se a confianca estiver abaixo do limite, marca escalonamento.

## Evolucao planejada

Curto prazo:

- calibrar confidence, handoff e ranking com perguntas reais
- acompanhar `pgvector` como default operacional do staging e manter rollback
  lexical documentado
- manter Chroma como prototipo local ou remover quando deixar de trazer valor
- melhorar a base de conhecimento usando os evals como regressao

Medio prazo:

- ampliar historico de conversas somente quando houver evidencia de necessidade
- usar feedback estruturado persistido para calibracao e backlog
- calibragem de thresholds e termos sensiveis de handoff
- roteamento entre dominios
- ativacao operacional da Meta WhatsApp Cloud API depois de smoke privado
- remocao de adapters temporarios quando a Meta estiver validada
