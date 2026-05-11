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

O retrieval ja passa por uma interface `VectorStore`. Hoje o adapter padrao e `LexicalVectorStore`; `ChromaStore` implementa o mesmo contrato como prototipo local; `pgvector` deve entrar como novo adapter sem alterar a orquestracao.

## `app/llm`

Abstracao dos modelos.

Responsabilidades:

- isolar provider de LLM
- permitir mock no desenvolvimento
- facilitar troca entre OpenAI, Anthropic ou open source

O provider mock ainda e o caminho usado pelo dominio padrao. O `LLMService` ja consegue rotear para `LLMWrapper` com OpenAI/Anthropic quando `domain.yaml` trocar `llm.provider`, mas a configuracao padrao segue em mock para desenvolvimento e testes.

## `app/orchestration`

Fluxo principal do agente.

Responsabilidades:

- recuperar contexto
- montar prompt
- chamar o provider
- calcular confianca
- decidir escalonamento

O `ChatFlowService` usa `prompt_builder.py` como ponto unico de montagem de prompt. Historico curto ainda esta preparado como contrato, mas permanece vazio ate existir persistencia de conversas.

O fluxo tambem retorna `request_id` e `error_code` quando ha falha observavel de retrieval ou provider.

## `app/handoff`

Camada de decisao de escalonamento humano.

Responsabilidades:

- escalar por baixa confianca
- escalar por pedido explicito de humano
- escalar por termos sensiveis configurados no dominio
- retornar motivos estruturados para automacoes futuras

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

- trocar `domain.yaml` para provider real quando houver API key configurada
- consolidar pipeline LangChain/Chroma com a ingestao atual ou manter como prototipo isolado
- integracao com PostgreSQL e pgvector
- implementar adapter `pgvector` no contrato `VectorStore`
- provider real de embeddings no caminho principal
- provider real de LLM no caminho principal

Medio prazo:

- historico de conversas
- feedback estruturado
- calibragem de thresholds e termos sensiveis de handoff
- roteamento entre dominios
- automacao com `n8n`
