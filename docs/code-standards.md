# Regras simples do codigo

Este documento define o minimo que cada parte do projeto deve respeitar.

## Regras gerais

- Cada arquivo deve ter um papel claro.
- Nomes devem refletir responsabilidade, nao implementacao acidental.
- Prefira funcoes e servicos pequenos, com entradas e saidas explicitas.
- Evite espalhar conhecimento de dominio por camadas genericas.
- Mantenha o MVP enxuto; nao introduza complexidade futura sem necessidade atual.

## Rotas

Arquivos em `app/api/routes/` devem:

- validar entrada
- chamar servicos
- traduzir erros para HTTP

Arquivos em `app/api/routes/` nao devem:

- conter regra de negocio longa
- acessar arquivo de dominio diretamente sem passar pela camada apropriada

## Schemas

Arquivos em `app/api/schemas/` devem:

- definir contratos claros de request e response
- usar tipos explicitos

## Core

Arquivos em `app/core/` devem:

- concentrar preocupacoes compartilhadas
- evitar dependencia em detalhes de dominio

## Dominio

Arquivos em `app/domain_engine/` e `domains/` devem:

- manter configuracao legivel
- facilitar extensao para novos setores
- permitir que a maior parte da especializacao aconteca sem mexer no core

## Ingestion

Arquivos em `app/ingestion/` devem:

- tratar documentos como dados versionados
- separar leitura, normalizacao e chunking sempre que isso trouxer clareza

## Retrieval

Arquivos em `app/retrieval/` devem:

- expor uma interface simples para buscar contexto
- esconder detalhes da estrategia de busca

## LLM

Arquivos em `app/llm/` devem:

- isolar provider externo
- facilitar mock e substituicao
- evitar acoplar o restante do sistema a SDKs especificas

## Orquestracao

Arquivos em `app/orchestration/` devem:

- coordenar o fluxo entre modulos
- evitar assumir detalhes de infraestrutura que pertencem a outras camadas

## Dominios novos

Ao criar um novo dominio:

- comece por `domain.yaml`
- adicione prompts claros
- organize bem artigos e FAQs
- mantenha nomes consistentes
- nao replique codigo se configuracao resolver

## Quando documentar

Documente sempre que houver mudanca em:

- arquitetura
- convencoes
- fluxo principal
- estrutura de dominio
