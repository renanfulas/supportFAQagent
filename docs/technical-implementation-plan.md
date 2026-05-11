# Plano Tecnico de Implementacao

Este documento detalha como executar o MVP do `supportFAQagent` por fase e por responsabilidade.

Ele complementa o [Plano Unico do MVP](mvp-plan.md) com tarefas tecnicas, contratos entre frentes, riscos, criterios de pronto e trilhas de SQL, seguranca, performance e debug.

## Principios de execucao

- Fazer o menor sistema que prove o fluxo RAG com qualidade.
- Manter o core Python independente de fornecedor sempre que isso for simples.
- Usar LangChain apenas onde ele reduz codigo real ou melhora manutencao.
- Tratar `PostgreSQL + pgvector` como vector store principal do MVP.
- Tratar `Chroma` como adapter local/prototipo enquanto `pgvector` nao estiver integrado.
- Toda frente deve entregar codigo integravel, documentado e testavel.

## Estado atual da main

A `main` ja possui algumas pecas importantes:

- `create_app()` em `app/main.py`
- smoke tests em `tests/test_app.py`
- `LLMWrapper` com OpenAI e Anthropic em `app/llm/wrapper.py`
- `get_embeddings()` em `app/retrieval/embeddings.py`
- `ChromaStore` em `app/retrieval/chroma_store.py`
- `RecursiveCharacterTextSplitter` no pipeline CSV em `app/ingestion/pipeline.py`
- `ticket_loader.py` para CSV de chamados
- `prompt_builder.py` em `app/orchestration/`

Ainda nao esta integrado ao caminho principal:

- `/chat` continua usando `RetrievalService` lexical e provider mock
- `prompt_builder.py` ja e chamado por `ChatFlowService`
- `LLMWrapper` ja esta integrado ao `LLMService`, mas o dominio padrao ainda usa `mock`
- handoff estruturado ja retorna motivos de escalonamento
- `ChromaStore` ainda nao e o retrieval oficial do endpoint `/chat`
- `domain.yaml` ainda aponta para `llm.provider: mock`

## Responsaveis

| Pessoa | Frente | Missao principal |
| --- | --- | --- |
| Silotto - TekZoom HG | VPS e infraestrutura | Ambiente, deploy, variaveis, rede, logs e operacao base |
| Alexandre Madeira | n8n e banco de dados | PostgreSQL, pgvector, persistencia, workflows n8n e integracoes |
| Juliano Barreto | LangChain e afins | Text splitter, loaders uteis e apoio no pipeline RAG |
| Renan | Arquitetura, orquestracao, testes e seguranca | Contratos, fluxo de chat, qualidade, hardening e coordenacao tecnica |

## Contratos entre frentes

## API interna

O backend deve expor contratos estaveis para automacoes e testes:

- `GET /health`
- `GET /domains`
- `GET /ingestion/{domain_name}/preview`
- `POST /chat`
- futuro `POST /ingest`
- futuro `POST /feedback`

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
  "domain": "suporte-vps-whatsapp",
  "answer": "texto final para o usuario",
  "confidence": 0.82,
  "escalated": false,
  "references": ["article_chunks.id ou source"]
}
```

## Configuracao por dominio

O `domain.yaml` deve ser a fronteira de configuracao por setor.

Campos esperados no MVP:

```yaml
llm:
  provider: openai
  model: gpt-4o-mini

embedding:
  provider: openai
  model: text-embedding-3-small
  dimensions: 1536

rag:
  top_k: 5
  chunk_size: 800
  chunk_overlap: 120
  confidence_threshold: 0.70
  history_turns: 4

security:
  redact_pii_in_logs: true
  block_prompt_injection: true
```

## Fase 1 - Base de providers e contratos

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

Criterio de pronto:

- Banco aceita conexao do backend.
- `CREATE EXTENSION IF NOT EXISTS vector;` validado.

## Juliano - LangChain

- Revisar as dependencias atuais `langchain`, `langchain-community`, `langchain-openai` e `langchain-anthropic`.
- Confirmar se todas sao necessarias no MVP ou se alguma pode sair depois da integracao.
- Evitar chains e memoria gerenciada nesta fase.

Criterio de pronto:

- Dependencia definida sem puxar arquitetura desnecessaria.

## Renan - Arquitetura e orquestracao

- Manter `LLMWrapper` integrado ao `LLMService` sem quebrar o mock usado nos testes.
- Trocar `domain.yaml` para provider real apenas quando houver API key valida no ambiente.
- Definir se `ChatFlowService.answer()` vira async ou se o wrapper tera chamada sincrona equivalente.
- Criar ou consolidar `BaseEmbeddingProvider`.
- Integrar `get_embeddings()` ao servico de retrieval quando o vector store oficial estiver pronto.
- Atualizar schemas de resposta quando necessario.
- Definir erros padrao de provider indisponivel, timeout e resposta vazia.

Criterio de pronto:

- `POST /chat` consegue chamar provider real em ambiente local.
- Falha de provider retorna erro rastreavel sem vazar secret.

## Fase 2 - Ingestao e chunking

Objetivo: transformar artigos e FAQs em chunks consistentes, prontos para embedding.

## Silotto - VPS

- Garantir permissao de leitura dos arquivos de dominio no deploy.
- Validar volume ou pasta onde conhecimento sera versionado.

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
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE articles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain_id UUID NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  source TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'markdown',
  content_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
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
- Criar preview de ingestao por dominio.
- Definir hash de conteudo para idempotencia.

Criterio de pronto:

- `GET /ingestion/{domain}/preview` mostra contagem consistente.
- Reprocessar o mesmo conteudo nao cria duplicacao logica.

## Fase 3 - Embeddings e retrieval vetorial

Objetivo: consultar contexto real no pgvector usando embeddings.

Nota de estado:
`ChromaStore` ja existe e pode continuar como prototipo local. O caminho de producao deve esperar a decisao final com `pgvector`, para nao criar duas fontes de verdade.

## Silotto - VPS

- Validar variaveis de API do provider de embeddings.
- Confirmar conectividade de saida para o provider, se for externo.
- Monitorar consumo de CPU/memoria durante ingestao.

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

## Juliano - LangChain

- Revisar se `OpenAIEmbeddings` e `HuggingFaceEmbeddings` atuais atendem o MVP.
- Garantir que o restante do app nao dependa diretamente de classes LangChain.
- Documentar trade-off da escolha.

## Renan - Orquestracao

- Criar interface `VectorStore`.
- Criar adapter para `ChromaStore` e futuro adapter para `pgvector` seguindo a mesma interface.
- Criar `RetrievalService` chamando `EmbeddingProvider` + `VectorStore` quando o adapter oficial estiver escolhido.
- Retornar `RetrievedChunk` com `id`, `source`, `title`, `text`, `score`.
- Definir fallback temporario se banco vetorial estiver indisponivel.

Criterio de pronto:

- Pergunta gera embedding.
- Retrieval retorna top-k chunks do dominio correto.
- Falha do banco gera erro rastreavel e nao resposta inventada.

## Fase 4 - Prompt builder, resposta e handoff

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
- Persistir `confidence`, `escalated`, `references` e erro tecnico quando houver.

SQL sugerido:

```sql
CREATE TABLE conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain_id UUID NOT NULL REFERENCES domains(id),
  session_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'bot',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  confidence DOUBLE PRECISION,
  escalated BOOLEAN NOT NULL DEFAULT false,
  references JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_conversations_session_domain
ON conversations(session_id, domain_id, updated_at DESC);

CREATE INDEX idx_messages_conversation_created
ON messages(conversation_id, created_at);
```

## Juliano - LangChain

- Nao usar `ConversationalRetrievalChain` nesta fase.
- Ajudar apenas no splitter/loaders se necessario.
- Revisar se prompt builder precisa de algum utilitario externo.

## Renan - Orquestracao, testes e seguranca

- Manter `prompt_builder.py` integrado ao `ChatFlowService`.
- Adicionar historico curto real por `history_turns` quando houver persistencia de conversas.
- Implementar confidence score inicial.
- Manter regras de handoff por threshold, pedido humano e termos sensiveis.
- Calibrar os termos com dados reais antes de expor canal publico.
- Criar testes do fluxo `/chat`.

Criterio de pronto:

- Uma pergunta respondida faz uma chamada ao LLM.
- Resposta inclui references.
- Baixa confianca marca `escalated=true`.

## Fase 5 - n8n, operacao e feedback

Objetivo: preparar integracoes externas sem mover inteligencia para fora do backend.

## Silotto - VPS

- Preparar container ou servico do n8n quando o nucleo estiver validado.
- Definir acesso seguro ao painel.
- Configurar reverse proxy, TLS e logs.

## Alexandre - n8n e banco

- Criar workflow `whatsapp-to-bot`.
- Criar workflow `escalation-notify`.
- Preparar `POST /feedback` quando o backend expuser contrato.
- Exportar workflows como JSON versionado, nao depender apenas de pasta runtime.

## Juliano - LangChain

- Apoiar ingestao futura de formatos adicionais se os tickets entrarem no pipeline.

## Renan - Arquitetura e seguranca

- Definir contrato de `POST /feedback`.
- Definir payload de escalonamento.
- Criar guia de integracao n8n.
- Validar que n8n nao carrega regra central do agente.

## Seguranca e privacidade

## Riscos principais

- Secrets em logs ou Git.
- PII em chunks, prompts ou mensagens persistidas.
- Prompt injection vindo de artigos, tickets ou usuario.
- Cross-domain retrieval por ausencia de filtro.
- Endpoint sem rate limit.
- Resposta inventada quando o contexto e fraco.

## Controles minimos do MVP

- `.env` fora do Git.
- Logs com PII mascarada.
- `domain_id` obrigatorio em toda busca vetorial.
- Prompt com regra explicita contra instrucao maliciosa no contexto.
- Timeout em providers externos.
- Rate limit nos endpoints publicos antes de expor na internet.
- Auditoria de eventos de escalonamento e falha de provider.

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
- Erros devem ter codigo interno estavel.
- Smoke tests devem cobrir health, domains, ingestion preview e chat.

## Matriz de dependencias

| Entrega | Depende de | Responsavel primario |
| --- | --- | --- |
| Provider real de LLM | API key e contrato de provider | Renan |
| Wrapper de embeddings | Modelo escolhido e secret configurado | Renan |
| Text splitter | Consolidar pipeline atual com ingestion oficial | Juliano |
| Schema de artigos/chunks | PostgreSQL + pgvector | Alexandre |
| Retrieval vetorial | Schema pgvector ou adapter Chroma temporario | Alexandre + Renan |
| Deploy do backend | VPS pronta | Silotto |
| Workflow WhatsApp | API `/chat` estavel | Alexandre |
| Handoff | Confidence e payload de resposta | Renan + Alexandre |
| Hardening | Deploy e endpoints expostos | Renan + Silotto |

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
- o plano de SQL permite rollback e evolucao incremental
- a seguranca minima esta pronta antes de expor canais publicos
