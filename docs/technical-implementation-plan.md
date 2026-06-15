# Plano Tecnico de Implementacao

Este documento detalha como executar o MVP do `supportFAQagent` por fase e por responsabilidade.

Ele complementa o [Plano Unico do MVP](mvp-plan.md) com tarefas tecnicas, contratos entre frentes, riscos, criterios de pronto e trilhas de SQL, seguranca, performance e debug.

Para comunicacao publica, README, PRs e tarefas de agentes, use tambem o
[Posicionamento do Produto](product-positioning.md). Ele define a promessa
comercial tecnica: reduzir repeticao no suporte, responder com conhecimento
versionado, preservar rastreabilidade e escalar quando faltar contexto.

Consulte tambem o runbook de staging e os contratos SQL do repositorio para a definicao de ambiente oficial, papel do `DATABASE_URL` e fronteira entre backend, banco e `n8n`.

## Principios de execucao

- Fazer o menor sistema que prove o fluxo RAG com qualidade.
- Manter o core Python independente de fornecedor sempre que isso for simples.
- Usar LangChain apenas onde ele reduz codigo real ou melhora manutencao.
- Tratar `PostgreSQL + pgvector` como vector store principal do MVP.
- Tratar `Chroma` como adapter local/prototipo; o caminho oficial de producao
  deve permanecer em `PostgreSQL + pgvector` quando estiver configurado e
  calibrado para o ambiente.
- Toda frente deve entregar codigo integravel, documentado e testavel.

## Estado atual do projeto

O projeto ja possui algumas pecas importantes:

- `create_app()` em `app/main.py`
- smoke tests em `tests/test_app.py`
- contratos de entrada com limites basicos para `/chat`, `/feedback` e ingestao preview
- `X-Request-ID` em todas as respostas HTTP para correlacao de logs e integracoes
- `LLMWrapper` com OpenAI e Anthropic em `app/llm/wrapper.py`
- `get_embeddings()` em `app/retrieval/embeddings.py`
- `ChromaStore` em `app/retrieval/chroma_store.py`
- `RecursiveCharacterTextSplitter` no pipeline CSV em `app/ingestion/pipeline.py`
- `ticket_loader.py` para CSV de chamados
- `prompt_builder.py` em `app/orchestration/`
- `POST /feedback` com persistencia confiavel quando `PERSISTENCE_BACKEND=postgres`
- `POST /ingestion/preview` para validar chunks por payload sem persistir
- contrato modular de dominio em `domain.yaml`, com persona, objetivo, regras, mensagens e handoff
- evals locais em `domains/suporte-vps-whatsapp/evals/cases.yaml`

Avancos confirmados no historico entre 13/05/2026 e 16/05/2026:

- dominio inicial configurado com provider real `openai`
- fallback classificado para falhas de provider
- `chat-ui` de texto para desenvolvimento e staging controlado
- `API_SECRET_KEY` obrigatoria fora de `development`
- rate limit no endpoint `/chat`
- handoff calibrado com motivos estruturados
- contrato de feedback expandido para contexto operacional
- adapter `PgVectorStore` e testes Python do contrato
- contrato SQL executavel para validacao de busca vetorial
- runbook e preflight da contingencia de VPS
- backend real PostgreSQL/pgvector conectado por `DATABASE_URL`
- writer operacional de ingestao persistente para artigos, chunks e embeddings
- staging privado validado com pgvector, embeddings reais e seeds artificiais
  removidos antes da calibragem

Estado consolidado do nucleo tecnico em 14/06/2026:

- `/chat` continua usando retrieval lexical como padrao seguro quando
  `RETRIEVAL_BACKEND` nao aponta para `pgvector`
- `RETRIEVAL_BACKEND=pgvector` ja ativa o caminho vetorial oficial em runtime
  com `DATABASE_URL` e dados ingeridos
- `prompt_builder.py` ja e chamado por `ChatFlowService`
- `LLMWrapper` ja esta integrado ao `LLMService` e o dominio padrao ja aponta para provider real
- handoff estruturado ja retorna motivos de escalonamento
- `RetrievalService` ja usa contrato `VectorStore`
- `/chat` ja retorna `request_id` e `error_code`
- `ChromaStore` continua como prototipo local e nao e o retrieval oficial do endpoint `/chat`
- `domain.yaml` ja aponta para `llm.provider: openai`
- `/feedback` persiste contexto confiavel quando `PERSISTENCE_BACKEND=postgres`
- conversas e mensagens sanitizadas persistem por dominio, canal e hash de
  sessao quando `PERSISTENCE_BACKEND=postgres`
- historico curto real entra no prompt como dado nao confiavel
- `/health/ready` separa banco, migrations, retrieval e outbox sem chamar LLM
- migrations forward-only, sanitizacao persistente e outbox transacional da
  Fase 0 estao implementadas no repositorio
- o rollout local real aplicou migrations `001-008`, confirmou expand/contract
  e terminou com `356 passed`; os hardenings locais foram concluidos em
  15/06/2026 e a aprovacao operacional ainda depende de provas em staging
- `POST /ingestion/preview` nao persiste artigos, chunks ou embeddings
- evals ja cobrem a linha de base atual do MVP com retrieval lexical, handoff calibrado e contrato de feedback atualizado
- a calibragem local com `pgvector` ja gerou baseline forte:
  `pgvector_gate.yaml=74/78` e `pgvector_curated.yaml=179/240`
- o staging oficial reproduziu exatamente os baselines:
  `pgvector_gate.yaml=74/78` e `pgvector_curated.yaml=179/240`
- as Fases 1 a 4 do nucleo tecnico estao concluidas
- a promocao do pgvector como default permanente passa a ser decisao
  operacional da Fase 5, com rollback para lexical

## Responsaveis

Ownership operacional atual da Fase 5:

| Pessoa | Frente | Missao principal |
| --- | --- | --- |
| Juliano Barreto | VPS, runtime e automacoes | Deploy, rede, logs, n8n, Evolution API, workflows, snapshots e recuperacao |
| Renan | Aplicacao, banco e integracao | Arquitetura, PostgreSQL, pgvector, persistencia, contratos, testes, seguranca e coordenacao |

Este mapa atual substitui as atribuicoes operacionais abaixo para trabalho
novo. As tabelas historicas permanecem como registro da execucao das Fases 1 a
4.

| Pessoa | Frente | Missao principal |
| --- | --- | --- |
| Silotto - TekZoom HG | VPS e infraestrutura | Ambiente, deploy, variaveis, rede, logs e operacao base |
| Alexandre Madeira | n8n e banco de dados | PostgreSQL, pgvector, persistencia, workflows n8n e integracoes |
| Juliano Barreto | LangChain e afins | Text splitter, loaders uteis e apoio no pipeline RAG |
| Renan | Arquitetura, orquestracao, testes e seguranca | Contratos, fluxo de chat, qualidade, hardening e coordenacao tecnica |

## Contratos entre frentes

Regra de fronteira para esta fase:

- Renan define contratos HTTP, schema SQL, migrations, persistencia, pgvector,
  testes de contrato e adapters de integracao
- Juliano opera VPS, n8n, Evolution API, rede, secrets, logs, snapshots e
  recuperacao
- mudancas que atravessam aplicacao e runtime exigem revisao conjunta

Coordenacao:

- Juliano opera staging, `DATABASE_URL`, secrets privados, conectividade,
  runtime e logs
- Renan responde por schema, migrations, indices, queries `pgvector` e
  persistencia
- qualquer resultado compartilhado deve ser sanitizado, sem IPs, hostnames,
  usuarios, portas administrativas, credenciais ou logs sensiveis

Leitura pratica do ponto atual:

- a frente de VPS foi coberta em contingencia para staging privado, com
  documentacao, hardening basico, utilitarios de validacao e relatorios
  sanitizados
- o pendente principal agora e manter a operacao reproduzivel, controlar
  capacidade de disco e preparar integracoes externas
- a frente de banco pertence a Renan; aplicacao de migration em staging exige
  snapshot e revisao conjunta com Juliano

## Modelo multi-dominio

O schema do projeto deve nascer como schema da plataforma de agentes por dominio, nao como schema especifico de `suporte-vps-whatsapp`.

O que deve permanecer generico no banco:

- dominios
- artigos e fontes
- chunks e embeddings
- conversas
- mensagens

O que deve ficar fora do schema central:

- regras especificas de suporte VPS
- logica especifica de vendas
- handoff especifico de onboarding
- detalhes operacionais de `n8n` ou canais externos

Direcao pratica:

- um unico PostgreSQL por ambiente
- `pgvector` no mesmo banco da aplicacao
- isolamento estrutural por `domain_id`
- configuracao e comportamento especifico em `domains/<domain>/`

## API interna

O backend deve expor contratos estaveis para automacoes e testes:

- `GET /health`
- `GET /domains`
- `GET /ingestion/{domain_name}/preview`
- `POST /ingestion/preview`
- `POST /chat`
- `POST /feedback`

Contrato minimo de `POST /chat`:

```json
{
  "message": "Como conectar o WhatsApp na Evolution API?",
  "session_id": "whatsapp:+5511999999999",
  "domain": "suporte-vps-whatsapp"
}
```

Resposta minima:

```json
{
  "request_id": "uuid-ou-header",
  "domain": "suporte-vps-whatsapp",
  "answer": "texto final para o usuario",
  "confidence": 0.82,
  "escalated": false,
  "handoff_reasons": [],
  "references": ["article_chunks.id ou source"],
  "error_code": null
}
```

Campos que devem permanecer estaveis para integracoes e persistencia
operacional:

- `request_id`
- `domain`
- `answer`
- `confidence`
- `escalated`
- `handoff_reasons`
- `references`
- `error_code`

Observacao de retrieval:

- `references` hoje e `list[str]` rastreavel e serializavel
- a troca de lexical para pgvector nao deve quebrar esse contrato
- metadados mais ricos de retrieval devem entrar como extensao futura, nao como ruptura do campo atual

## Configuracao por dominio

O `domain.yaml` deve ser a fronteira de configuracao por setor.

Campos esperados no MVP:

```yaml
contract_version: 1
name: suporte-vps-whatsapp
display_name: Suporte VPS e WhatsApp
description: Agente para duvidas recorrentes de VPS, WhatsApp e automacoes.
owner: Renan
default_language: pt-BR

behavior:
  persona: agente de suporte tecnico claro e direto
  primary_goal: orientar usuarios com respostas seguras
  answer_guidelines:
    - responda em linguagem simples
  out_of_scope:
    - acesso a senhas, tokens ou chaves privadas

response:
  tone: simples
  max_context_chunks: 5
  max_answer_length: short

handoff:
  confidence_threshold: 0.55
  explicit_human_phrases:
    - falar com humano
  sensitive_terms:
    - senha
    - bloqueio

knowledge:
  sources:
    - knowledge/articles
    - knowledge/faqs

llm:
  provider: openai
  model: gpt-4o-mini

embedding:
  provider: openai
  model: text-embedding-3-small
  dimensions: 1536
```

Observacao:

- O provider padrao do dominio inicial ja foi movido para `openai`, mas o ambiente ainda depende de `OPENAI_API_KEY` valida para resposta automatica completa.
- O historico curto ja usa `CONVERSATION_HISTORY_MESSAGES`; configuracao
  especifica por dominio, como `rag.history_turns`, pode entrar depois sem
  substituir o isolamento atual por dominio, canal e hash de sessao.
- Campos como `chunk_overlap` e politicas de seguranca mais detalhadas podem
  entrar depois, mas ainda nao sao contrato implementado.

## Fase 1 - Base de providers e contratos

Status: concluida.

Objetivo: ligar os wrappers ja criados ao fluxo principal, sem acoplar o core a SDKs externos.

## Silotto - VPS

- Validar Python runtime da VPS.
- Definir como variaveis serao injetadas no deploy.
- Preparar `.env` de ambiente com placeholders seguros.
- Confirmar acesso a logs do backend.
- Definir URL interna do backend para n8n.

Criterio de pronto:

- Backend sobe na VPS com `GET /health` respondendo.
- Secrets nao ficam versionados.

## Alexandre - Banco

- Confirmar versao do PostgreSQL.
- Habilitar extensao `vector`.
- Definir `DATABASE_URL`.
- Criar primeira migration relacional quando a estrategia estiver fechada.
- Seguir o ambiente oficial do projeto, sem usar laboratorio externo como fonte de verdade.

Criterio de pronto:

- Banco aceita conexao do backend.
- `CREATE EXTENSION IF NOT EXISTS vector;` validado.

## Juliano - LangChain

- Revisar as dependencias atuais `langchain-core`, `langchain-text-splitters`, `langchain-openai`, `langchain-anthropic` e o extra opcional `chroma`.
- Confirmar se todas sao necessarias no MVP ou se alguma pode sair depois da integracao.
- Evitar chains e memoria gerenciada nesta fase.

Criterio de pronto:

- Dependencia definida sem puxar arquitetura desnecessaria.

## Renan - Arquitetura e orquestracao

- Manter `LLMWrapper` integrado ao `LLMService` sem quebrar o mock usado nos testes.
- Endurecer fallback e observabilidade quando o provider real nao puder responder por falta de credencial, timeout ou erro externo.
- Definir se `ChatFlowService.answer()` vira async ou se o wrapper tera chamada sincrona equivalente.
- Criar ou consolidar `BaseEmbeddingProvider`.
- Integrar `get_embeddings()` ao servico de retrieval quando o vector store oficial estiver pronto.
- Atualizar schemas de resposta quando necessario.
- Definir erros padrao de provider indisponivel, timeout e resposta vazia.

Criterio de pronto:

- `POST /chat` consegue chamar provider real em ambiente local.
- Falha de provider retorna erro rastreavel sem vazar secret.

Status em 16/05/2026:

- considerado essencialmente concluido para a frente de aplicacao
- nao retrabalhar provider real, fallback ou exigencia de segredo sem bug concreto

## Fase 2 - Ingestao e chunking

Status: concluida.

Objetivo: transformar artigos e FAQs em chunks consistentes, prontos para embedding.

## Silotto - VPS

- Garantir permissao de leitura dos arquivos de dominio no deploy.
- Validar volume ou pasta onde conhecimento sera versionado.
- Fechar com o time o PostgreSQL oficial do staging HostGator, incluindo `DATABASE_URL`, secrets e conectividade privada.

## Alexandre - Banco

- Preparar tabelas para artigos e chunks.
- Garantir idempotencia na ingestao por `domain`, `source` e hash de conteudo.
- Criar indexes basicos para consultas por dominio e artigo.

SQL sugerido:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE domains (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  owner TEXT NOT NULL DEFAULT 'community',
  status TEXT NOT NULL DEFAULT 'active',
  config_version INT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE articles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain_id UUID NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  source TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'markdown',
  external_id TEXT,
  content_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (domain_id, source)
);

CREATE TABLE article_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  article_id UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  domain_id UUID NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
  chunk_index INT NOT NULL,
  chunk_text TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  token_estimate INT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  embedding VECTOR(1536),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (article_id, chunk_index)
);

CREATE INDEX idx_articles_domain_status ON articles(domain_id, status);
CREATE INDEX idx_articles_domain_source_type_external ON articles(domain_id, source_type, external_id);
CREATE INDEX idx_chunks_domain_article ON article_chunks(domain_id, article_id);
CREATE INDEX idx_chunks_metadata_gin ON article_chunks USING gin(metadata);
```

Vector index apos volume inicial:

```sql
CREATE INDEX idx_chunks_embedding_cosine
ON article_chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

Observacao:

- Criar o indice vetorial depois de inserir dados iniciais costuma ser mais rapido.
- Ajustar `lists` com base no volume real.
- `external_id` e `metadata` preparam ingestao futura de fontes externas sem acoplar o core a um setor especifico.

## Juliano - LangChain

- Consolidar o `RecursiveCharacterTextSplitter` ja usado em `app/ingestion/pipeline.py`.
- Expor funcao simples e reutilizavel: `split_text(text, chunk_size, chunk_overlap)`.
- Garantir que o output mantenha `chunk_index` e metadata.
- Nao introduzir `Document` do LangChain como tipo central do projeto se isso acoplar demais.

Criterio de pronto:

- Mesmo texto sempre gera chunks previsiveis.
- Chunks vazios ou duplicados sao descartados.

## Renan - Organizacao e testes

- Adaptar `IngestionService` para usar splitter configuravel.
- Decidir como `ticket_loader.py` convive com artigos e FAQs locais.
- Criar testes de chunking para texto curto, longo e vazio.
- Manter preview de ingestao por dominio.
- Manter preview de ingestao por payload em `POST /ingestion/preview`.
- Definir hash de conteudo para idempotencia.

Criterio de pronto:

- `GET /ingestion/{domain}/preview` mostra contagem consistente.
- `POST /ingestion/preview` permite revisar chunking antes de persistir.
- Reprocessar o mesmo conteudo nao cria duplicacao logica.

Status em 16/05/2026:

- chunking e preview avancaram de forma suficiente para o MVP atual
- evitar retrabalho em `chunk_index`, metadata de chunk e isolamento basico de dependencias LangChain sem evidencias novas

## Fase 3 - Embeddings e retrieval vetorial

Status: concluida para o MVP.

Objetivo: consultar contexto real no pgvector usando embeddings.

Nota de estado:
`ChromaStore` ja existe e pode continuar como prototipo local. O caminho de producao deve esperar a decisao final com `pgvector`, para nao criar duas fontes de verdade.

Status consolidado em 11/06/2026:

- o contrato do `PgVectorStore`, os testes Python e a validacao SQL ja existem
- o backend real por `DATABASE_URL` ja foi conectado e validado em staging
  privado com embeddings reais do dominio inicial
- a ingestao persistente existe como comando operacional explicito em
  `scripts/ingest_domain_pgvector.py`
- a calibragem local aceitou `pgvector_gate.yaml` como gate forte de
  laboratorio com `74/78`
- `pgvector_curated.yaml` ficou em `179/240` e segue como backlog de
  calibracao, nao como bloqueio de release
- o staging oficial reproduziu a gate em `74/78` e a curated em `179/240`
- confidence, threshold, ranking e handoff estao aceitos para o MVP
- evitar retrabalho reimplementando adapter, reabrindo contrato de `references`
  ou promovendo `Chroma` a fonte oficial

## Silotto - VPS

- Validar variaveis de API do provider de embeddings.
- Confirmar conectividade de saida para o provider, se for externo.
- Monitorar consumo de CPU/memoria durante ingestao.
- Provisionar o banco oficial do staging HostGator conforme a definicao operacional vigente do projeto.

## Alexandre - Banco

- Implementar escrita de embeddings em `article_chunks.embedding`.
- Criar query de top-k por similaridade filtrando por dominio.
- Avaliar `EXPLAIN ANALYZE` antes e depois do indice vetorial.

SQL de busca sugerido:

```sql
SELECT
  id,
  article_id,
  chunk_text,
  metadata,
  1 - (embedding <=> :query_embedding) AS similarity
FROM article_chunks
WHERE domain_id = :domain_id
  AND embedding IS NOT NULL
ORDER BY embedding <=> :query_embedding
LIMIT :top_k;
```

Regras de banco:

- Sempre filtrar por `domain_id`.
- Nunca buscar em todos os dominios por padrao.
- Guardar `metadata` suficiente para rastrear fonte.
- Evitar PII em `chunk_text` quando vier de chamados reais.
- Manter `pgvector` no mesmo PostgreSQL da aplicacao, nao em banco separado.

## Juliano - LangChain

- Revisar se `OpenAIEmbeddings` e `HuggingFaceEmbeddings` atuais atendem o MVP.
- Garantir que o restante do app nao dependa diretamente de classes LangChain.
- Documentar trade-off da escolha.

## Renan - Orquestracao

- Manter interface `VectorStore`.
- Criar adapter `pgvector` seguindo a mesma interface.
- Criar `RetrievalService` chamando `EmbeddingProvider` + `VectorStore` quando o adapter oficial estiver escolhido.
- Retornar `RetrievedChunk` com `id`, `source`, `title`, `text`, `score`.
- Definir fallback temporario se banco vetorial estiver indisponivel.

Criterio de pronto:

- Pergunta gera embedding.
- Retrieval retorna top-k chunks do dominio correto.
- Falha do banco gera erro rastreavel e nao resposta inventada.

## Fase 4 - Prompt builder, resposta e handoff

Status: concluida para o nucleo tecnico do MVP.

Objetivo: responder com contexto recuperado, uma chamada ao LLM e escalonamento claro.

## Prompt spec do agente

Objetivo:

- Responder duvidas recorrentes com base apenas no contexto recuperado e nas regras do dominio.

Nao objetivos:

- Inventar procedimentos sem fonte.
- Resolver cobranca, disputa legal ou acesso sensivel sem humano.
- Fingir certeza quando o contexto for fraco.

Contrato do prompt:

```text
Papel:
Voce e um agente de suporte do dominio {domain_name}.

Regra principal:
Responda somente com base no contexto fornecido. Se o contexto for insuficiente, diga isso e recomende escalonamento.

Contexto:
{retrieved_context}

Historico recente:
{recent_history}

Pergunta do usuario:
{question}

Formato:
- resposta direta em portugues do Brasil
- checklist curto quando houver passos
- sem mencionar detalhes internos do RAG
- se houver risco de bloqueio, seguranca, cobranca ou falta de contexto, sinalize escalonamento
```

Casos de teste do prompt:

- Pergunta com contexto forte deve responder com passos.
- Pergunta fora do dominio deve escalar.
- Pedido para ignorar instrucoes deve ser recusado.
- Pergunta com PII deve evitar repetir dados sensiveis.
- Pergunta ambigua deve pedir uma informacao objetiva ou escalar.

## Silotto - VPS

- Garantir logs de request com `request_id`.
- Definir limites de timeout para chamadas externas.

## Alexandre - Banco

- Preparar tabelas de conversas e mensagens.
- Persistir `confidence`, `escalated`, `references` da API no campo `message_references` e erro tecnico quando houver.

SQL sugerido:

```sql
CREATE TABLE conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain_id UUID NOT NULL REFERENCES domains(id),
  channel TEXT NOT NULL DEFAULT 'api',
  session_hash TEXT NOT NULL,
  session_hash_version TEXT NOT NULL,
  external_conversation_id TEXT,
  status TEXT NOT NULL DEFAULT 'bot',
  last_message_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  turn_id UUID NOT NULL,
  request_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  provider TEXT,
  confidence DOUBLE PRECISION,
  escalated BOOLEAN NOT NULL DEFAULT false,
  message_references JSONB NOT NULL DEFAULT '[]'::jsonb,
  error_code TEXT,
  latency_ms INT,
  redaction_version TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_conversations_active_session
ON conversations(domain_id, channel, session_hash)
WHERE status IN ('bot', 'handoff_pending', 'human_active');

CREATE INDEX idx_conversations_domain_channel_external
ON conversations(domain_id, channel, external_conversation_id);

CREATE INDEX idx_messages_conversation_created
ON messages(conversation_id, created_at);
```

Observacao:

- `channel` e `external_conversation_id` preparam a plataforma para WhatsApp,
  web, Zoom, CRM, email ou outros canais sem criar tabelas por setor.
- `session_id` bruto nao deve ser persistido; somente HMAC versionado.
- `provider`, `error_code` e `latency_ms` permitem observabilidade e auditoria sem depender de campos especificos do primeiro dominio.

## Juliano - LangChain

- Nao usar `ConversationalRetrievalChain` nesta fase.
- Ajudar apenas no splitter/loaders se necessario.
- Revisar se prompt builder precisa de algum utilitario externo.

## Renan - Orquestracao, testes e seguranca

- Manter `prompt_builder.py` integrado ao `ChatFlowService`.
- Manter historico curto real, sanitizado e isolado por dominio, canal e hash
  de sessao.
- Implementar confidence score inicial.
- Manter regras de handoff por threshold, pedido humano e termos sensiveis.
- Calibrar os termos com dados reais antes de expor canal publico.
- Criar testes do fluxo `/chat`.
- Manter evals locais do dominio inicial com perguntas reais recorrentes.

Criterio de pronto:

- Uma pergunta respondida faz uma chamada ao LLM.
- Resposta inclui references.
- Baixa confianca marca `escalated=true`.

## Fase 5 - n8n, operacao e feedback

Status: proxima fase operacional e pos-MVP, em andamento.

Objetivo: preparar integracoes externas sem mover inteligencia para fora do backend.

Nota de sequencia:

- a comparacao oficial foi concluida em 11/06/2026
- a gate de staging reproduziu o baseline local em `74/78`
- esta fase agora concentra operacao, persistencia, n8n e evolucao pos-MVP

## Juliano - VPS, n8n e Evolution API

- Operar container ou servico do n8n.
- Definir acesso seguro ao painel, reverse proxy, TLS, rede e logs.
- Validar e ativar os workflows versionados `whatsapp-to-bot`,
  `escalation-notify` e `web-otp-delivery`.
- Configurar Evolution API apenas no runtime privado.

## Renan - Aplicacao, banco e seguranca

- Manter contrato e persistencia confiavel de `POST /feedback`.
- Manter schema, migrations, sanitizacao, outbox e dispatcher.
- Definir payload de escalonamento e guia de integracao n8n.
- Validar que n8n nao carrega regra central do agente.
- Tratar domain evals como gate deterministico, sem provider real bloqueando a
  validacao de banco.

## Seguranca e privacidade

## Riscos principais

- Secrets em logs ou Git.
- PII em chunks, prompts ou mensagens persistidas.
- Prompt injection vindo de artigos, tickets ou usuario.
- Cross-domain retrieval por ausencia de filtro.
- Endpoint sem rate limit.
- Resposta inventada quando o contexto e fraco.
- Filesystem raiz da VPS sem espaco por crescimento de cache de build Docker.

## Controles minimos do MVP

- `.env` fora do Git.
- Logs com PII mascarada.
- `domain_id` obrigatorio em toda busca vetorial.
- Prompt com regra explicita contra instrucao maliciosa no contexto.
- Timeout em providers externos.
- Rate limit nos endpoints publicos antes de expor na internet.
- Auditoria de eventos de escalonamento e falha de provider.
- Alerta de uso de disco e limpeza controlada de cache de build Docker.

Risco operacional observado em 11/06/2026:

- o filesystem raiz do staging chegou a `100%`
- o PostgreSQL nao iniciou porque nao conseguiu criar `postmaster.pid`
- a limpeza exclusiva de cache de build Docker liberou `8.35 GB`
- o ambiente terminou a rodada ainda em `90%`, com aproximadamente `1.8 GB`
  livres
- volumes e dados do PostgreSQL nao devem ser removidos durante manutencao

Checklist de hardening:

- Nenhuma API key em arquivo versionado.
- Nenhum stack trace bruto para usuario final.
- Nenhum log com telefone, email ou token sem mascara.
- `session_id` tratado como dado sensivel.
- Validacao server-side de `domain`.
- Limite de tamanho para `message`.
- CORS restrito quando houver frontend.

## Performance

Metas praticas do MVP:

- `GET /health`: abaixo de 50ms em ambiente normal.
- `POST /chat` sem LLM: abaixo de 300ms.
- `POST /chat` com LLM: dominado pelo provider, mas com overhead local baixo.
- Ingestao em batch para evitar uma chamada de embedding por chunk quando possivel.

Cuidados:

- Nao recalcular embeddings de conteudo inalterado.
- Usar top-k pequeno no inicio, normalmente 3 a 5.
- Limitar tamanho do contexto enviado ao LLM.
- Indexar por `domain_id` e por vetor.
- Medir queries com `EXPLAIN ANALYZE` antes de mexer no indice.
- Registrar tempo por etapa: embedding, retrieval, LLM e total.

## Debug e observabilidade

Todo fluxo de chat deve conseguir responder:

- qual dominio foi usado
- qual `request_id` rastreia a chamada
- quais chunks foram recuperados
- qual score cada chunk teve
- qual provider foi chamado
- quanto tempo cada etapa levou
- por que houve escalonamento

Campos recomendados de log:

- `request_id`
- `session_id_hash`
- `domain`
- `route`
- `embedding_ms`
- `retrieval_ms`
- `llm_ms`
- `total_ms`
- `confidence`
- `escalated`
- `error_code`

Regras de debug:

- Logs nao podem vazar prompt completo com PII em producao.
- `session_id_hash` deve usar HMAC com segredo privado; sem segredo persistente,
  usar chave efemera por processo em vez de produzir hash simples enumeravel.
- Erros devem ter codigo interno estavel.
- Smoke tests devem cobrir health, domains, ingestion preview e chat.

## Matriz de dependencias

| Entrega | Depende de | Responsavel primario |
| --- | --- | --- |
| Provider real de LLM | API key e contrato de provider | Renan |
| Wrapper de embeddings | Modelo escolhido e secret configurado | Renan |
| Text splitter | Consolidar pipeline atual com ingestion oficial | Juliano |
| Schema, migrations e persistencia | PostgreSQL + pgvector | Renan |
| Retrieval vetorial | Schema pgvector e adapter oficial | Renan |
| Deploy do backend | VPS pronta | Juliano |
| Workflow WhatsApp | API `/chat` estavel e ingress assinado | Juliano |
| Handoff | Confidence, outbox e payload estavel | Renan + Juliano |
| Hardening | Aplicacao, deploy e endpoints expostos | Renan + Juliano |
| Evals do dominio | Casos reais e criterios de qualidade | Renan |

## Backlog pos-MVP

- Ingestao de chamados historicos com curadoria.
- PII scrubber mais robusto.
- Feedback loop com avaliacao humana.
- Dashboard simples de qualidade.
- n8n para canais adicionais.
- Reavaliar memoria conversacional.
- Reavaliar `ConversationalRetrievalChain` apenas com evidencias de necessidade.

## Criterio final de saude tecnica

O MVP esta tecnicamente saudavel quando:

- cada frente consegue trabalhar sem bloquear as outras por falta de contrato
- dados vetoriais sempre respeitam dominio
- o agente sabe dizer "nao tenho contexto suficiente"
- falhas externas sao observaveis e nao viram resposta inventada
- o plano de SQL permite evolucao incremental forward-only e recuperacao por
  snapshot; nao existe rollback SQL automatico
- a seguranca minima esta pronta antes de expor canais publicos
