# Plano tecnico - Qualidade de retrieval vetorial

## Objetivo

Preparar e integrar o retrieval vetorial oficial usando o contrato `VectorStore`,
com filtro obrigatorio por dominio, scores rastreaveis e fallback seguro quando
o banco vetorial estiver indisponivel.

Esta frente depende da decisao operacional de `PostgreSQL + pgvector`, mas pode
avancar em contrato, testes e adapter sem assumir detalhes finais de migration.

## Problema observado

O fluxo `/chat` ainda usa retrieval lexical como caminho ativo. O projeto ja tem
`VectorStore`, `LexicalVectorStore`, `ChromaStore` e embeddings por dominio, mas
o adapter `pgvector` ainda nao e o caminho oficial.

Lacunas principais:

- implementar adapter `pgvector` sem quebrar `RetrievalService`
- garantir filtro por dominio em toda busca
- preservar `references` como `list[str]`
- retornar score e fonte rastreaveis internamente
- definir fallback quando banco ou embedding falhar
- evitar Chroma como segunda fonte de verdade em producao

## Escopo

Entram nesta frente:

- revisar `app/retrieval/vector_store.py`
- revisar `app/retrieval/service.py`
- criar ou integrar adapter `pgvector`
- revisar `app/retrieval/embeddings.py`
- ajustar modelos em `app/retrieval/models.py`
- adicionar testes de isolamento por dominio
- manter contratos de `/chat` estaveis

Ficam fora desta frente:

- desenhar sozinho schema SQL final
- mover migrations sem alinhamento com Alexandre
- remover Chroma sem decisao explicita
- criar fallback entre multiplos bancos vetoriais
- mudar formato publico de `references` sem versao nova
- ingerir historico com PII sem curadoria

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

## Implementacao sugerida

Passos recomendados:

- manter `VectorStore.search(domain, query, top_k)` como interface publica
- adicionar adapter `PgVectorStore` sem alterar chamada do `ChatFlowService`
- converter resultado SQL para `RetrievedChunk`
- filtrar por `domain_id` ou equivalente antes de ordenar por vetor
- mapear erros de banco para `RetrievalError`
- manter `LexicalVectorStore` como fallback local somente quando configurado

## Conteudo proibido

Esta frente nao deve:

- buscar chunks sem filtro de dominio
- expor query SQL ou stack trace ao usuario
- gravar PII de chamados reais sem limpeza e curadoria
- usar Chroma e pgvector como fontes oficiais simultaneas sem contrato
- quebrar consumidores que esperam `references: list[str]`

## Testes a adicionar ou revisar

Casos minimos:

- retrieval respeita `max_context_chunks`
- falha do store vira `RetrievalError`
- busca vetorial nunca retorna chunks de outro dominio
- resultados preservam `source` ou referencia equivalente
- score e ordenacao sao coerentes em teste controlado
- `/chat` continua respondendo quando o retrieval retorna lista vazia

## Validacao

Durante a frente:

```powershell
python -m pytest tests/test_retrieval_service.py
python -m pytest tests/db
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

## Estimativa

- Alinhar contrato com schema de banco: 45 a 90 minutos
- Implementar adapter e mapeamento: 2 a 4 horas
- Testar isolamento, falhas e evals: 1,5 a 3 horas

Total esperado: 4 a 8,5 horas.
