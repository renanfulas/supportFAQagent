# Plano Unico do MVP

## Objetivo

Este documento consolida a direcao do MVP do `supportFAQagent` em um unico plano de execucao.

A meta e evitar frentes paralelas conflitantes e alinhar o time sobre:

- o que entra agora
- o que depende de outras pessoas
- o que fica preparado para depois

O detalhamento tecnico por fase e por responsavel esta em [Plano Tecnico de Implementacao](technical-implementation-plan.md).

## Decisoes aprovadas

- O nucleo segue em Python com FastAPI.
- A arquitetura continua modular por dominio.
- O primeiro dominio segue sendo `suporte-vps-whatsapp`.
- O fluxo do MVP sera RAG simples, linear e previsivel.
- O MVP nao usara `ConversationalRetrievalChain`.
- O `n8n` continua sendo camada de automacao externa, nao parte do nucleo de inteligencia.
- LangChain, se usado, entra apenas como apoio pontual e nao como espinha dorsal do sistema.

## Estado atual do projeto

Hoje o repositorio ja possui:

- API FastAPI inicial
- app factory com `create_app()`
- estrutura modular de `app/`
- dominio inicial versionado em `domains/suporte-vps-whatsapp/`
- ingestao local de artigos e FAQs
- retrieval lexical temporario
- provider de LLM mock
- `LLMService` integrado ao `LLMWrapper` para OpenAI/Anthropic quando o dominio trocar o provider
- `ChatFlowService` integrado ao `prompt_builder.py`
- handoff estruturado por baixa confianca, pedido humano e termos sensiveis
- retrieval desacoplado por interface `VectorStore`
- `/chat` com `request_id` e `error_code`
- smoke tests para health, dominios, preview de ingestao e chat mock
- utilitarios LangChain para CSV, chunking, embeddings, Chroma e prompt builder
- documentacao base de arquitetura e contribuicao

Importante:
Os utilitarios LangChain/Chroma ja existem na `main`, mas ainda nao sao o caminho principal do endpoint `/chat`.

## Responsabilidades

Para este MVP, as frentes ficam organizadas assim:

- `Silotto - TekZoom HG`
  Responsavel pela VPS e infraestrutura base. Se houver necessidade de ajuda operacional ou custo extra de ambiente, essa frente sinaliza para o time.

- `Alexandre Madeira`
  Responsavel pelo `n8n` e pelo banco de dados. Isso inclui a camada de automacao externa e a frente de persistencia em andamento com `PostgreSQL + pgvector`.

- `Juliano Barreto`
  Responsavel pelo LangChain e componentes relacionados. Essa frente deve manter o uso de LangChain enxuto e alinhado ao escopo do MVP.

- `Renan`
  Responsavel por arquitetura, orquestracao, organizacao do projeto, testes, seguranca e apoio transversal ao restante do time.

## Dependencias em andamento fora desta frente

Estas entregas estao sendo conduzidas por outro desenvolvedor e devem ser tratadas como dependencia do plano:

- PostgreSQL
- pgvector
- persistencia relacional principal
- base vetorial principal para retrieval

Este plano nao duplica essa implementacao. Ele prepara a aplicacao para integrar com ela e evita transformar Chroma em uma segunda base de producao paralela sem decisao explicita do time.

## Escopo do MVP desta frente

Estas sao as entregas que devem entrar agora nesta linha de trabalho:

- provider real de LLM com interface desacoplada
- wrapper de embeddings com suporte a provider configuravel
- integrar `LLMWrapper` e embeddings ao fluxo principal
- consolidar chunking com `RecursiveCharacterTextSplitter`
- pipeline simples de ingestao de artigos, FAQs e CSV curado
- integracao do retrieval com o vector store definido pelo time
- integrar prompt builder simples com contexto e historico curto manual
- confidence score inicial por heuristica
- handoff para humano por threshold configuravel
- configuracao por dominio em `domain.yaml`

## Uso de LangChain no MVP

LangChain entra no MVP apenas de forma enxuta.

Componentes aprovados:

- `RecursiveCharacterTextSplitter`
- loaders utilitarios apenas se houver ganho real para formatos adicionais
- abstracoes leves de embeddings, se ajudarem a padronizar providers
- adapter Chroma apenas como apoio local/prototipo enquanto pgvector nao esta integrado ao fluxo principal

Componentes que nao entram agora:

- `ConversationalRetrievalChain`
- memoria conversacional gerenciada pelo LangChain
- chains complexas para multiplas chamadas por turno
- orquestracao central dependente de LangChain

Direcao: LangChain como biblioteca auxiliar, nao como fundacao obrigatoria do sistema.

## Fluxo funcional do MVP

1. A API recebe a pergunta.
2. O dominio e resolvido pela request ou pelo padrao.
3. O dominio carrega configuracoes de prompt, retrieval e handoff.
4. A pergunta vira embedding pelo provider configurado.
5. O retrieval consulta o vector store principal.
6. O sistema seleciona os top-k chunks mais relevantes.
7. O prompt builder monta o contexto com:
   - pergunta atual
   - contexto recuperado
   - historico recente curto, se existir
8. O LLM responde em uma unica chamada.
9. O sistema calcula a confianca.
10. Se a confianca estiver abaixo do threshold, marca escalonamento.

## Fora do escopo do MVP

Para manter a entrega enxuta, estes itens ficam fora do MVP:

- `ConversationalRetrievalChain`
- memoria longa gerenciada por framework
- ingestao massiva de chamados historicos sem curadoria
- pipeline automatico completo de anonimizacao de PII
- fallback entre multiplos vector stores
- coexistencia de `Chroma` e `pgvector` no mesmo MVP
- automacao completa com `n8n` para todos os canais
- fine-tuning de modelos
- feedback loop automatico para retreinamento

## Posicionamento sobre Chroma

Como `PostgreSQL + pgvector` esta sendo encaminhado por outro desenvolvedor, este plano assume `pgvector` como caminho principal do MVP.

A `main` ja contem um adapter `ChromaStore` e um pipeline CSV para Chroma. Isso muda o status de Chroma: ele existe como trilha tecnica auxiliar, mas nao deve virar fonte oficial de producao sem uma decisao do time.

Por isso:

- `Chroma` pode ser usado para prototipo local e validacao de pipeline
- `Chroma` nao deve duplicar a estrategia final de `pgvector`
- o endpoint `/chat` nao deve depender de Chroma ate a decisao de vector store estar fechada
- o codigo deve ficar desacoplado o suficiente para trocar `Chroma` por `pgvector` sem reescrever orquestracao

## Papel do n8n

O `n8n` continua valido, mas como fase posterior do MVP funcional do nucleo.

Uso previsto:

- integrar WhatsApp e outros canais externos
- acionar `/chat`, `/ingest` e `/feedback`
- lidar com notificacoes e roteamento operacional

Nao deve:

- carregar regras centrais de inteligencia
- substituir a logica principal do backend Python

## Sequencia recomendada de implementacao

## Fase 1

- trocar o dominio de `mock` para provider real quando houver API key configurada
- integrar o wrapper de embeddings ao retrieval principal
- atualizar `domain.yaml` com configuracoes reais de LLM, embedding e retrieval

## Fase 2

- consolidar chunking com `RecursiveCharacterTextSplitter` na ingestao oficial
- unificar ingestao de artigos/FAQs com pipeline CSV curado
- manter suporte simples aos formatos atuais sem acoplar o core ao Chroma

## Fase 3

- integrar retrieval vetorial com a entrega de `pgvector`
- implementar adapter `pgvector` seguindo o contrato `VectorStore`
- decidir se `ChromaStore` permanece apenas como adapter local ou sera removido apos pgvector
- ajustar top-k, threshold e formato de evidencias
- validar performance basica do fluxo fim a fim

## Fase 4

- preparar historico curto real quando houver persistencia de conversas
- calibrar confidence score inicial com dados reais
- revisar termos sensiveis de handoff por dominio

## Fase 5

- documentar a configuracao operacional
- preparar hooks para futura integracao com `n8n`
- listar backlog pos-MVP

## Riscos principais e mitigacao

## Dependencia externa do vector store

Risco:
O trabalho de `pgvector` pode evoluir em ritmo diferente.

Mitigacao:
- manter interface de retrieval desacoplada
- validar primeiro com provider e fluxo pronto
- integrar assim que a camada vetorial estiver disponivel

## Excesso de abstracao cedo demais

Risco:
Introduzir muito LangChain ou automacao antes de validar o fluxo base.

Mitigacao:
- usar apenas componentes pontuais
- preservar servicos simples e rastreaveis

## Dados de conhecimento de baixa qualidade

Risco:
Artigos e FAQs fracos derrubam a qualidade da resposta.

Mitigacao:
- priorizar curadoria do dominio inicial
- comecar por conteudo enxuto e confiavel

## Escalonamento pouco calibrado

Risco:
O bot responder quando devia escalar, ou escalar demais.

Mitigacao:
- threshold configuravel por dominio
- observacao manual no inicio
- ajuste iterativo apos testes reais

## Criterios de pronto do MVP

O MVP desta frente sera considerado pronto quando:

- houver provider real de LLM funcionando
- houver embeddings reais funcionando
- o chunking estiver integrado
- o retrieval vetorial estiver conectado ao vector store principal
- o fluxo `/chat` responder com contexto e confidence
- o handoff estiver sinalizado de forma consistente
- a configuracao do dominio inicial estiver documentada

## Resultado esperado

Ao final deste plano, o projeto tera:

- um fluxo RAG de MVP simples e funcional
- integracao com a base vetorial principal do time
- uma arquitetura que continua desacoplada por dominio
- espaco limpo para evoluir depois com `n8n`, historico mais sofisticado e automacoes adicionais
