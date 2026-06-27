# Plano Unico do MVP

## Objetivo

Este documento consolida a direcao do MVP do `supportFAQagent` em um unico plano de execucao.

A meta de produto e entregar um agente de suporte que reduza perguntas repetidas, responda com base em conhecimento versionado e escale para humano quando faltar contexto.

A meta de execucao e evitar frentes paralelas conflitantes e alinhar o time sobre:

- o que entra agora
- o que depende de outras pessoas
- o que fica preparado para depois

O detalhamento tecnico por fase e por responsavel esta em [Plano Tecnico de Implementacao](technical-implementation-plan.md).

## Decisoes aprovadas

- O nucleo segue em Python com FastAPI.
- A arquitetura continua modular por dominio.
- O primeiro dominio segue sendo `suporte-vps-whatsapp`.
- A comunicacao do projeto deve seguir `docs/product-positioning.md`: comercial tecnica, honesta sobre limites e focada em seguranca operacional.
- O fluxo do MVP sera RAG simples, linear e previsivel.
- O MVP nao usara `ConversationalRetrievalChain`.
- A direcao atual de WhatsApp e Meta WhatsApp Cloud API nativa; `n8n` foi
  removido do projeto e Evolution permanece apenas como ponte legada, sem gate
  ativo.
- LangChain, se usado, entra apenas como apoio pontual e nao como espinha dorsal do sistema.

## Estado atual do projeto

Hoje o repositorio ja possui:

- API FastAPI inicial
- app factory com `create_app()`
- estrutura modular de `app/`
- dominio inicial versionado em `domains/suporte-vps-whatsapp/`
- ingestao local de artigos e FAQs
- retrieval lexical como padrao seguro para local/CI e rollback operacional
- retrieval PostgreSQL/pgvector promovido como default operacional do staging
- provider real configurado por dominio, com fallback seguro quando faltar credencial ou o provider falhar
- `LLMService` integrado ao `LLMWrapper` para OpenAI/Anthropic no dominio atual
- `ChatFlowService` integrado ao `prompt_builder.py`
- handoff estruturado por baixa confianca, pedido humano, termos sensiveis e falha tecnica observavel
- retrieval desacoplado por interface `VectorStore`
- `/chat` com `request_id` e `error_code`
- `X-Request-ID` em todas as respostas HTTP
- `POST /feedback` com persistencia confiavel quando `PERSISTENCE_BACKEND=postgres`
- `POST /ingestion/preview` para revisar chunking por payload, sem persistir
- contrato modular de dominio com persona, diretrizes, escopo e mensagens padrao
- evals locais para calibrar o dominio inicial com perguntas reais recorrentes
- smoke tests para health, dominios, preview de ingestao e chat com fallback seguro
- utilitarios LangChain para CSV, chunking, embeddings, Chroma e prompt builder
- writer operacional para persistir artigos, chunks e embeddings no pgvector
- documentacao base de arquitetura e contribuicao

Importante:
`pgvector` e o default operacional do staging quando `DATABASE_URL`, embeddings
e dados ingeridos estao presentes. A gate oficial de staging foi validada com
`76/78`; `lexical` permanece como default local/CI e rollback documentado.

Estado consolidado em 11/06/2026:

- baseline local da gate: `74/78`
- baseline local da curated: `179/240`
- staging real da gate: `74/78`
- staging real da curated: `179/240`
- `pgvector_gate.yaml` foi aceita como gate estavel do MVP
- as Fases 1 a 4 do nucleo tecnico estao concluidas
- a Fase 5 passa a ser a proxima fase operacional e pos-MVP

Avanco integrado pelo PR `#64` em 12/06/2026:

- conversas, mensagens e feedback persistem de forma sanitizada quando
  `PERSISTENCE_BACKEND=postgres`
- historico curto real entra no prompt isolado por dominio, canal e hash de
  sessao
- migrations `001-008`, outbox transacional, retencao e readiness separado
  estao implementados
- PostgreSQL/pgvector real local passou pelo rollout expand/contract e pela
  suite completa com `356 passed`
- a Fase 0 continua `not_approved` ate provar restore cronometrado em ambiente
  isolado; `n8n` foi removido do projeto e nao e gate do MVP

## Responsabilidades

Para este MVP, as frentes ficam organizadas assim:

- `Juliano Barreto`
  Responsavel pela VPS, deploy, runtime, rede, logs, secrets, restore,
  conectividade e apoio pontual em LangChain. `n8n` foi removido; qualquer
  legado Evolution fica sob responsabilidade operacional, nao como plano ativo
  do MVP.

- `Renan`
  Responsavel por arquitetura, orquestracao, PostgreSQL, pgvector,
  persistencia, contratos, testes, seguranca, documentacao e integracao final.

O ownership atual substitui as atribuicoes operacionais antigas a Alexandre e
Silotto. Autoria historica de migrations e documentos permanece preservada.

## Dependencias coordenadas entre frentes

Renan responde por PostgreSQL, pgvector, persistencia, schema, migrations e
indices. Juliano responde pelo runtime onde esses componentes operam. Aplicar
migrations, promover pgvector ou alterar infraestrutura exige preflight,
snapshot e validacao conjunta.

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

Estado atual:

1. A API recebe a pergunta.
2. O dominio e resolvido pela request ou pelo padrao.
3. O dominio carrega configuracoes de prompt, retrieval e handoff.
4. O retrieval lexical padrao busca chunks nos documentos locais quando
   `RETRIEVAL_BACKEND=pgvector` nao esta configurado.
5. O sistema seleciona os top-k chunks mais relevantes.
6. O prompt builder monta o contexto com:
   - pergunta atual
   - contexto recuperado
   - historico recente curto, se existir
7. O provider configurado por dominio tenta responder usando o contexto recuperado.
8. Se o provider nao puder responder, o sistema devolve fallback seguro com `provider_error`.
9. O sistema calcula a confianca.
10. Se a confianca estiver abaixo do threshold, marca escalonamento.

Estado validado com pgvector:

1. A pergunta vira embedding pelo provider configurado.
2. O retrieval consulta o vector store principal.
3. O sistema retorna chunks do dominio correto com score rastreavel.
4. O LLM real responde em uma unica chamada usando o contexto recuperado.

O caminho acima ja foi validado em staging privado com dados reais do dominio
inicial. O staging oficial fechou `76/78` na gate e passou a usar `pgvector`
como default operacional, preservando rollback para lexical.

## Fora do escopo do MVP

Para manter a entrega enxuta, estes itens ficam fora do MVP:

- `ConversationalRetrievalChain`
- memoria longa gerenciada por framework
- ingestao massiva de chamados historicos sem curadoria
- pipeline automatico completo de anonimizacao de PII
- fallback entre multiplos vector stores
- coexistencia de `Chroma` e `pgvector` no mesmo MVP
- automacao completa por canais externos antes da Meta nativa ser validada
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

## Papel das integracoes WhatsApp

A direcao atual e tratar WhatsApp como canal externo com Meta WhatsApp Cloud
API nativa. `n8n` foi removido do projeto; Evolution permanece apenas como ponte
legada ate decisao explicita.

Uso previsto para a fundacao atual:

- receber webhooks da Meta por rota propria e validacao de assinatura
- enviar mensagens pela Graph API usando adapter isolado
- entregar OTP por Meta quando o template estiver aprovado
- usar Hermes apenas como adapter temporario de entrega OTP quando necessario

Nao deve:

- carregar regras centrais de inteligencia
- substituir a logica principal do backend Python
- acessar banco, prompt, RAG ou regras de dominio

## Sequencia recomendada de implementacao

## Fase 1

Status: concluida.

- estabilizar o uso do provider real com credenciais de ambiente e observabilidade de falhas
- integrar o wrapper de embeddings ao retrieval principal
- atualizar `domain.yaml` com configuracoes reais de LLM, embedding e retrieval

## Fase 2

Status: concluida.

- consolidar chunking com `RecursiveCharacterTextSplitter` na ingestao oficial
- unificar ingestao de artigos/FAQs com pipeline CSV curado
- manter suporte simples aos formatos atuais sem acoplar o core ao Chroma
- manter `POST /ingestion/preview` nao persistente por contrato; usar o writer
  operacional separado para ingestao pgvector

## Fase 3

Status: concluida para o MVP.

- integrar retrieval vetorial com a entrega de `pgvector`
- implementar adapter `pgvector` seguindo o contrato `VectorStore`
- decidir se `ChromaStore` permanece apenas como adapter local ou sera removido apos pgvector
- ajustar top-k, threshold e formato de evidencias com dados reais
- validar performance basica do fluxo fim a fim em staging privado

## Fase 4

Status: concluida para o nucleo tecnico do MVP.

- manter o historico curto real e sua sanitizacao como regressao coberta
- consolidar `confidence_threshold` e sinais de handoff com dados reais
- manter a `pgvector_gate.yaml` como regressao oficial do MVP
- manter evals locais como regressao de qualidade antes de mudar prompts, retrieval ou provider

## Fase 5 - Proxima fase operacional e pos-MVP

Status: em andamento.

- manter a configuracao operacional reproduzivel
- executar restore cronometrado em ambiente isolado
- validar a fundacao Meta WhatsApp em smoke privado antes de ativacao real
- validar em staging a persistencia, migrations, sanitizacao e outbox
  implementadas na Fase 0
- acompanhar `pgvector` como default operacional do staging e preservar rollback
  para `RETRIEVAL_BACKEND=lexical`
- monitorar disco, banco, containers e logs da VPS
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

## Capacidade de disco da VPS

Risco:
O staging chegou a `100%` de uso do filesystem raiz por cache de build Docker,
impedindo o PostgreSQL de iniciar.

Mitigacao:
- manter alerta de uso de disco
- definir limpeza periodica de cache de build Docker
- preservar volumes e dados do PostgreSQL durante limpezas
- revisar capacidade antes de promover o ambiente para producao

## Criterios de pronto do MVP

O MVP desta frente sera considerado pronto quando:

- houver provider real de LLM funcionando com fallback seguro quando indisponivel
- houver embeddings reais funcionando
- o chunking estiver integrado
- o retrieval vetorial estiver conectado ao vector store principal
- o fluxo `/chat` responder com contexto e confidence
- o handoff estiver sinalizado de forma consistente
- a configuracao do dominio inicial estiver documentada
- a `pgvector_gate.yaml` em staging ficar acima do criterio normal aceito

## Resultado esperado

Ao final deste plano, o projeto tera:

- um fluxo RAG de MVP simples e funcional
- integracao com a base vetorial principal do time
- uma arquitetura que continua desacoplada por dominio
- espaco limpo para evoluir depois com Meta WhatsApp nativa, historico mais
  sofisticado e automacoes adicionais
