# Plano tecnico - Qualidade de retrieval vetorial

Archive: incorporado ao MVP. Este documento preserva decisoes e criterios da
frente; o trabalho ativo esta nas fontes atuais de promocao e calibragem.

## Objetivo

Preparar a qualidade do retrieval vetorial oficial usando o contrato
`VectorStore`, com filtro obrigatorio por dominio, scores rastreaveis e falha
segura quando embedding, banco vetorial ou adapter estiver indisponivel.

Esta frente deve fechar a qualidade do caminho oficial com `PostgreSQL +
pgvector`, sem assumir ownership de schema, migrations, queries finais ou
armazenamento operacional da frente de banco.

## Estado observado

O fluxo `/chat` usa `RetrievalService` com lexical como padrao seguro, mas ja
pode usar `PgVectorStore` quando `RETRIEVAL_BACKEND=pgvector` esta configurado.
O projeto ja tem `VectorStore`, `LexicalVectorStore`, `ChromaStore`,
`RetrievedChunk`, o contrato Python do `PgVectorStore`, validacao SQL
executavel do shape da busca vetorial, backend PostgreSQL real por
`DATABASE_URL` e writer operacional de ingestao persistente.

`build_vector_store(domain)` em `app/retrieval/service.py` e o ponto de selecao
entre lexical e `pgvector`. O caminho vetorial foi validado em staging privado
com dados reais do dominio inicial, depois da remocao de seeds artificiais de
smoke.

O `ChromaStore` implementa a interface e preserva metadados em `add_chunks`, mas
`search(domain, query, top_k)` nao filtra por dominio hoje. Por isso, Chroma deve
continuar descrito como prototipo local, nao como store oficial de producao.

Entregas ja concluidas nesta frente:

- adapter `PgVectorStore` implementado como contrato Python
- mapeamento de falhas para `RetrievalError`
- preservacao de `RetrievedChunk(source, title, text, score)`
- validacao Python do adapter em `tests/test_pgvector_store.py`
- validacao SQL executavel em `tests/db/validate_pgvector_search.sql`
- documentacao do contrato SQL em
  `docs/runbooks/pgvector-retrieval-contract.md`
- backend real de leitura PostgreSQL/pgvector conectado por `DATABASE_URL`
- selecao por `RETRIEVAL_BACKEND=pgvector` validada em staging privado
- writer explicito de ingestao em `app/ingestion/pgvector_writer.py`,
  preparado para persistir documentos locais, chunks e embeddings no schema
  multi-dominio existente sem alterar migrations
- script operacional `scripts/ingest_domain_pgvector.py` para rodar a ingestao
  persistente apenas quando `DATABASE_URL` e chave de embeddings estiverem
  configurados no ambiente privado

Backlog continuo desta frente:

- transformar a validacao operacional em uma rotina reproduzivel de release
- preservar `references` como `list[str]`
- retornar score e fonte rastreaveis internamente
- repetir a query oficial e os gates em cada promocao relevante
- manter o fallback lexical testado quando banco ou embedding falhar
- evitar Chroma como segunda fonte de verdade em producao
- calibrar thresholds com conteudo real, nao apenas seeds sinteticos
- manter o formato publico do `/chat` estavel: `request_id`, `domain`,
  `answer`, `confidence`, `escalated`, `handoff_reasons`, `references` e
  `error_code`

## Escopo

Entram nesta frente:

- revisar `app/retrieval/vector_store.py`
- revisar `app/retrieval/service.py`
- revisar `app/retrieval/pgvector_store.py`
- revisar `app/retrieval/embeddings.py`
- ajustar modelos em `app/retrieval/models.py`
- adicionar ou fortalecer testes de isolamento por dominio
- manter contratos de `/chat` estaveis
- manter `ChatFlowService` sem conhecimento de SQL, pgvector ou detalhes de
  persistencia

Ficam fora desta frente:

- alterar schema SQL final sem revisar contratos e impacto operacional
- aplicar migrations sem snapshot e alinhamento com Juliano
- alterar tabelas, indices ou extensoes sem gate SQL e rollback operacional
- remover Chroma sem decisao explicita
- criar fallback automatico entre multiplos bancos vetoriais
- mudar formato publico de `references` sem versao nova
- ingerir historico com PII sem curadoria
- transformar `n8n` em camada de inteligencia ou ranking

## Contrato de retrieval esperado

Para uma pergunta dentro de um dominio, o retrieval deve:

- gerar embedding quando o adapter exigir
- buscar somente chunks do dominio resolvido
- retornar top-k configurado pelo dominio
- preservar fonte rastreavel para `references`
- calcular ou repassar score de similaridade
- falhar de forma observavel, sem inventar contexto

## Arquivos alvo

```text
app/retrieval/vector_store.py
app/retrieval/service.py
app/retrieval/pgvector_store.py
app/retrieval/models.py
app/retrieval/embeddings.py
app/retrieval/chroma_store.py
app/retrieval/lexical_store.py
app/ingestion/pgvector_writer.py
app/orchestration/chat_flow.py
scripts/ingest_domain_pgvector.py
tests/test_retrieval_service.py
tests/test_chroma_store.py
tests/test_pgvector_store.py
tests/test_pgvector_ingestion_writer.py
tests/db/test_04_vector_search.sql
tests/db/test_05_isolation.sql
tests/db/validate_pgvector_search.sql
docs/runbooks/pgvector-retrieval-contract.md
docs/integration-contracts.md
docs/technical-implementation-plan.md
```

Observacao de ownership:

- Este plano pode orientar os arquivos acima e os testes relacionados.
- Nesta tarefa, o unico arquivo editado deve ser este plano.
- Mudancas em schema SQL, migrations e persistencia real precisam ser alinhadas
  com a frente de banco.

## Implementacao sugerida

Passos recomendados desta fase:

- manter `VectorStore.search(domain, query, top_k)` como interface publica do
  adapter
- manter `PgVectorStore` sem alterar chamada do `ChatFlowService`
- converter resultado SQL para `RetrievedChunk`
- filtrar por `domain_id` ou equivalente antes de ordenar por vetor
- mapear erros de banco para `RetrievalError`
- plugar um `search_backend` real ao contrato atual do adapter
- usar `build_vector_store(domain)` como ponto de selecao do adapter quando o
  caminho oficial sair do lexical
- manter `LexicalVectorStore` como caminho local/temporario somente quando
  configurado
- manter `ChromaStore` como prototipo local enquanto ele nao provar isolamento
  por dominio e enquanto pgvector for a fonte oficial planejada
- manter ingestao persistente como comando operacional explicito, nao como
  efeito colateral de `/chat` ou `/ingestion/preview`
- usar o subconjunto de colunas ja validado no banco oficial para `domains`,
  `articles` e `article_chunks`, sem assumir campos ainda nao presentes em
  staging

Contrato minimo do adapter `PgVectorStore`:

- receber dominio resolvido, pergunta e `top_k`
- gerar ou receber o embedding da pergunta via provider configurado no dominio
- resolver `domain_id` de forma deterministica sem buscar em todos os dominios
- executar busca filtrada por dominio antes de ordenar por distancia vetorial
- retornar `RetrievedChunk(source, title, text, score)` sem expor tipos SQL para
  a orquestracao
- preservar referencia serializavel para `ChatFlowService` montar
  `references: list[str]`
- propagar falhas como `RetrievalError` para que `/chat` retorne erro
  rastreavel e escalonamento seguro

## Conteudo proibido

Esta frente nao deve:

- buscar chunks sem filtro de dominio
- expor query SQL ou stack trace ao usuario
- gravar PII de chamados reais sem limpeza e curadoria
- usar Chroma e pgvector como fontes oficiais simultaneas sem contrato
- quebrar consumidores que esperam `references: list[str]`
- deixar `ChromaStore.search()` virar producao sem filtro por dominio
- exigir que `ChatFlowService` conheca `domain_id`, SQL ou pgvector

## Testes a adicionar ou revisar

Casos minimos:

- retrieval respeita `max_context_chunks`
- falha do store vira `RetrievalError`
- `PgVectorStore` converte linhas do backend para `RetrievedChunk`
- `PgVectorStore` rejeita linha sem `source` rastreavel ou `text`
- busca vetorial nunca retorna chunks de outro dominio
- resultados preservam `source` ou referencia equivalente
- score e ordenacao sao coerentes em teste controlado
- `/chat` continua respondendo quando o retrieval retorna lista vazia
- `build_vector_store(domain)` nao tenta gerar embeddings sem credencial quando
  o caminho ativo ainda for lexical
- `ChromaStore.add_chunks()` preserva `source`, `id`, `chunk_index` e
  `token_estimate` sem acoplar o core a `Document` do LangChain
- `ChromaStore.search()` so pode ser promovido se houver metadado e filtro de
  dominio testado

Sobre `tests/db`:

- os arquivos em `tests/db/*.sql` sao scripts SQL de contrato para extensoes,
  schema, idempotencia, busca vetorial e isolamento
- eles validam a intencao do contrato pgvector, mas nao substituem testes Python
  do adapter nem ownership de migrations
- `test_04_vector_search.sql` deve continuar cobrindo busca por similaridade com
  filtro por `domain_id`
- `test_05_isolation.sql` deve evoluir para provar que dados de outro dominio
  nao aparecem em uma busca real, nao apenas que uma tabela esta vazia
- `validate_pgvector_search.sql` deve continuar como script executavel via
  `psql`, com fixtures proprias, shape `source/title/text/score`, exclusao de
  `embedding IS NULL` e exclusao de artigos inativos

## Validacao

Durante a frente:

```powershell
python -m pytest tests/test_retrieval_service.py
python -m pytest tests/test_chroma_store.py
python -m pytest tests/test_pgvector_store.py
```

Validacao de scripts SQL, quando houver banco local preparado pela frente de
banco:

```powershell
psql $env:DATABASE_URL -f tests/db/test_01_extensions.sql
psql $env:DATABASE_URL -f tests/db/test_02_schema.sql
psql $env:DATABASE_URL -f tests/db/test_03_idempotency.sql
psql $env:DATABASE_URL -f tests/db/test_04_vector_search.sql
psql $env:DATABASE_URL -f tests/db/test_05_isolation.sql
psql $env:DATABASE_URL -f tests/db/validate_pgvector_search.sql
```

Validacao completa antes de commit:

```powershell
python -m compileall app scripts tests
python -m pytest
python -m app.evals.run_domain_eval suporte-vps-whatsapp
```

## Criterios de pronto

- O adapter vetorial segue `VectorStore`.
- Toda busca filtra por dominio.
- `references` continua serializavel e compativel com `/chat`.
- Falhas de embedding ou banco sao rastreaveis.
- O contrato Python do adapter e o contrato SQL da busca estao alinhados.
- Chroma permanece apenas prototipo/local, salvo decisao contraria.
- Testes provam isolamento entre dominios.
- `ChatFlowService` continua desacoplado de SQL, pgvector e persistencia.
- `RetrievedChunk` continua suficiente para prompt, confidence e references:
  `source`, `title`, `text` e `score`.
- A fronteira com PostgreSQL fica clara: esta frente valida contrato e adapter;
  a frente de banco define schema, migrations, indices, extensoes e operacao.

## Proximo Uso

Nao reimplementar adapter ou conexao. Use este plano para revisar regressao,
isolamento entre dominios e qualidade antes de promover mudancas em retrieval.
