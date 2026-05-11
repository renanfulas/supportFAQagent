# Arquitetura

## Visao geral

O projeto e uma plataforma em Python para agentes de atendimento por dominio. A mesma base tecnica deve suportar setores diferentes, trocando principalmente:

- artigos e FAQs
- prompts
- regras de escalonamento
- configuracao do dominio

O primeiro dominio e `suporte-vps-whatsapp`.

## Principios da arquitetura

- O nucleo do sistema deve ser reutilizavel entre dominios.
- O comportamento especifico de cada area deve entrar por configuracao e conteudo.
- O fluxo de atendimento deve continuar simples enquanto o MVP amadurece.
- O projeto deve poder evoluir para RAG vetorial sem reescrever a API.

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

## `app/retrieval`

Busca de contexto para resposta.

Responsabilidades:

- localizar trechos relevantes
- ranquear contexto
- entregar evidencias para o fluxo de chat

Hoje o fluxo `/chat` ainda usa retrieval lexical. A `main` tambem possui utilitarios de embeddings e um adapter `ChromaStore`, mas essa trilha ainda nao esta ligada ao fluxo principal. Como o `PostgreSQL + pgvector` esta em andamento por outra frente, Chroma deve ser tratado como adapter local/prototipo ate a decisao final de vector store do MVP.

## `app/llm`

Abstracao dos modelos.

Responsabilidades:

- isolar provider de LLM
- permitir mock no desenvolvimento
- facilitar troca entre OpenAI, Anthropic ou open source

O provider mock ainda e o caminho usado pelo fluxo atual de chat. A `main` ja possui um `LLMWrapper` com OpenAI/Anthropic, mas ele precisa ser integrado ao `LLMService` e configurado por dominio.

## `app/orchestration`

Fluxo principal do agente.

Responsabilidades:

- recuperar contexto
- montar prompt
- chamar o provider
- calcular confianca
- decidir escalonamento

A `main` ja possui um `prompt_builder.py`, mas o `ChatFlowService` ainda monta o prompt internamente. Uma proxima etapa e unificar o prompt builder com o fluxo real para evitar dois caminhos de prompt.

## `domains/`

Camada de especializacao por setor.

Cada dominio deve concentrar:

- `domain.yaml`
- prompts
- artigos
- FAQs
- exemplos futuros

Com isso, um novo setor deve exigir pouco codigo novo e muita configuracao boa.

## Fluxo atual do MVP

1. A API recebe uma pergunta.
2. O sistema resolve o dominio informado ou usa o padrao.
3. O `domain_engine` carrega regras e fontes de conhecimento.
4. O `ingestion` le os documentos e gera chunks.
5. O `retrieval` busca os trechos mais proximos da pergunta.
6. O `orchestration` monta o prompt com contexto.
7. O `llm` gera a resposta pelo provider mock atual.
8. O sistema calcula confianca.
9. Se a confianca estiver abaixo do limite, marca escalonamento.

## Evolucao planejada

Curto prazo:

- integrar `LLMWrapper` ao fluxo real de chat
- integrar `prompt_builder.py` ao `ChatFlowService`
- consolidar pipeline LangChain/Chroma com a ingestao atual ou manter como prototipo isolado
- integracao com PostgreSQL e pgvector
- provider real de embeddings no caminho principal
- provider real de LLM no caminho principal

Medio prazo:

- historico de conversas
- feedback estruturado
- regras mais ricas de handoff
- roteamento entre dominios
- automacao com `n8n`
