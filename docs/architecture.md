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

No MVP, os documentos sao locais. Depois, essa camada pode aceitar CMS, banco ou sincronizacao externa.

## `app/retrieval`

Busca de contexto para resposta.

Responsabilidades:

- localizar trechos relevantes
- ranquear contexto
- entregar evidencias para o fluxo de chat

Hoje a busca e lexical. A estrutura ja prepara a troca por embeddings com pgvector.

## `app/llm`

Abstracao dos modelos.

Responsabilidades:

- isolar provider de LLM
- permitir mock no desenvolvimento
- facilitar troca entre OpenAI, Anthropic ou open source

## `app/orchestration`

Fluxo principal do agente.

Responsabilidades:

- recuperar contexto
- montar prompt
- chamar o provider
- calcular confianca
- decidir escalonamento

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
7. O `llm` gera a resposta.
8. O sistema calcula confianca.
9. Se a confianca estiver abaixo do limite, marca escalonamento.

## Evolucao planejada

Curto prazo:

- persistencia com PostgreSQL
- pgvector
- provider real de embeddings
- provider real de LLM

Medio prazo:

- historico de conversas
- feedback estruturado
- regras mais ricas de handoff
- roteamento entre dominios
