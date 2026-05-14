# Plano tecnico - Qualidade de retrieval vetorial

## Objetivo

Preparar a qualidade do retrieval vetorial oficial usando o contrato
`VectorStore`, com filtro obrigatorio por dominio, scores rastreaveis e falha
segura quando embedding, banco vetorial ou adapter estiver indisponivel.

Esta frente deve alinhar o contrato Python com a decisao operacional de
`PostgreSQL + pgvector`, sem assumir ownership de schema, migrations, queries
finais ou armazenamento operacional da frente de banco.

## Problema observado

O fluxo `/chat` ainda usa `RetrievalService` com `LexicalVectorStore` como
caminho ativo. O projeto ja tem `VectorStore`, `LexicalVectorStore`,
`ChromaStore`, `RetrievedChunk` e embeddings por dominio, mas o adapter
`pgvector` ainda nao existe como caminho oficial.

Tambem existe `build_vector_store(domain)` em `app/retrieval/service.py`, que ja
resolve embeddings do dominio e documenta o ponto futuro para trocar para
`PgVectorStore`, mas o construtor atual de `RetrievalService` ainda instancia
`LexicalVectorStore()` diretamente quando nenhum adapter e injetado.

O `ChromaStore` implementa a interface e preserva metadados em `add_chunks`, mas
`search(domain, query, top_k)` nao filtra por dominio hoje. Por isso, Chroma deve
continuar descrito como prototipo local, nao como store oficial de producao.

Lacunas principais:

- implementar adapter `pgvector` sem quebrar `RetrievalService`
- garantir filtro por dominio em toda busca
- preservar `references` como `list[str]`
- retornar score e fonte rastreaveis internamente
- definir fallback quando banco ou embedding falhar
- evitar Chroma como segunda fonte de verdade em producao
- alinhar a factory `build_vector_store(domain)` com o caminho ativo quando o
  adapter oficial existir
- manter o formato publico do `/chat` estavel: `request_id`, `domain`,
  `answer`, `confidence`, `escalated`, `handoff_reasons`, `references` e
  `error_code`

## Escopo

Entram nesta frente:

- revisar `app/retrieval/vector_store.py`
- revisar `app/retrieval/service.py`
- criar ou integrar adapter `pgvector`
- revisar `app/retrieval/embeddings.py`
- ajustar modelos em `app/retrieval/models.py`
- adicionar ou fortalecer testes de isolamento por dominio
- manter contratos de `/chat` estaveis
- manter `ChatFlowService` sem conhecimento de SQL, pgvector ou detalhes de
  persistencia

Ficam fora desta frente:

- desenhar sozinho schema SQL final
- mover migrations sem alinhamento com Alexandre
- assumir ownership de tabelas, indices, extensoes ou migrations PostgreSQL
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
app/retrieval/models.py
app/retrieval/embeddings.py
app/retrieval/chroma_store.py
app/retrieval/lexical_store.py
app/orchestration/chat_flow.py
tests/test_retrieval_service.py
tests/test_chroma_store.py
tests/db/test_04_vector_search.sql
tests/db/test_05_isolation.sql
docs/integration-contracts.md
docs/technical-implementation-plan.md
```

Observacao de ownership:

- Este plano pode orientar os arquivos acima e os testes relacionados.
- Nesta tarefa, o unico arquivo editado deve ser este plano.
- Mudancas em schema SQL, migrations e persistencia real precisam ser alinhadas
  com a frente de banco.

## Implementacao sugerida

Passos recomendados:

- manter `VectorStore.search(domain, query, top_k)` como interface publica do
  adapter
- adicionar adapter `PgVectorStore` sem alterar chamada do `ChatFlowService`
- converter resultado SQL para `RetrievedChunk`
- filtrar por `domain_id` ou equivalente antes de ordenar por vetor
- mapear erros de banco para `RetrievalError`
- usar `build_vector_store(domain)` como ponto de selecao do adapter quando o
  caminho oficial sair do lexical
- manter `LexicalVectorStore` como caminho local/temporario somente quando
  configurado
- manter `ChromaStore` como prototipo local enquanto ele nao provar isolamento
  por dominio e enquanto pgvector for a fonte oficial planejada

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

## Validacao

Durante a frente:

```powershell
python -m pytest tests/test_retrieval_service.py
python -m pytest tests/test_chroma_store.py
```

Validacao de scripts SQL, quando houver banco local preparado pela frente de
banco:

```powershell
psql $env:DATABASE_URL -f tests/db/test_01_extensions.sql
psql $env:DATABASE_URL -f tests/db/test_02_schema.sql
psql $env:DATABASE_URL -f tests/db/test_03_idempotency.sql
psql $env:DATABASE_URL -f tests/db/test_04_vector_search.sql
psql $env:DATABASE_URL -f tests/db/test_05_isolation.sql
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
- Chroma permanece apenas prototipo/local, salvo decisao contraria.
- Testes provam isolamento entre dominios.
- `ChatFlowService` continua desacoplado de SQL, pgvector e persistencia.
- `RetrievedChunk` continua suficiente para prompt, confidence e references:
  `source`, `title`, `text` e `score`.
- A fronteira com PostgreSQL fica clara: esta frente valida contrato e adapter;
  a frente de banco define schema, migrations, indices, extensoes e operacao.

## Estimativa

- Alinhar contrato com schema de banco: 45 a 90 minutos
- Implementar adapter e mapeamento: 2 a 4 horas
- Testar isolamento, falhas e evals: 1,5 a 3 horas

Total esperado: 4 a 8,5 horas.
