# Plano tecnico - Qualidade de ingestao e chunking

## Objetivo

Consolidar a ingestao de artigos, FAQs e conteudo curado em chunks previsiveis,
idempotentes e prontos para embedding, sem acoplar o core ao banco ou ao
LangChain como espinha dorsal.

Esta frente pode rodar em paralelo a `pgvector`, porque prepara o shape dos
chunks e valida o preview antes da persistencia real.

## Problema observado

O projeto ja possui ingestao local, `POST /ingestion/preview`, splitter em
`app/ingestion/chunking.py`, pipeline CSV e utilitarios LangChain. O risco agora
e criar caminhos paralelos de chunking que gerem resultados diferentes para o
mesmo conteudo.

Lacunas principais:

- garantir que artigos locais e payloads do preview usem regras compativeis
- descartar chunks vazios e duplicados de forma previsivel
- preservar `source`, `title` e `chunk_index`
- preparar hash de conteudo para idempotencia futura
- deixar claro o limite entre preview sem persistencia e ingestao persistente

## Escopo

Entram nesta frente:

- revisar `app/ingestion/chunking.py`
- revisar `app/ingestion/service.py`
- revisar `app/ingestion/pipeline.py`
- revisar `app/ingestion/ticket_loader.py`
- ajustar contratos em `app/api/schemas/ingestion.py`
- atualizar testes de preview e chunking
- documentar regras em `docs/integration-contracts.md` se o payload mudar

Ficam fora desta frente:

- escrever em PostgreSQL
- gerar embeddings
- executar jobs assicronos de ingestao
- criar painel de curadoria
- ingerir massa historica sem curadoria
- tornar `Document` do LangChain tipo central do projeto

## Contrato de chunk esperado

Todo chunk utilizavel pelo RAG deve manter:

- `domain`
- `source`
- `title`
- `text`
- `chunk_index`
- metadados simples e serializaveis quando existirem

No futuro, a persistencia pode adicionar IDs, hash e timestamps, mas nao deve
quebrar os campos basicos acima.

## Arquivos alvo

```text
app/api/routes/ingestion.py
app/api/schemas/ingestion.py
app/ingestion/chunking.py
app/ingestion/models.py
app/ingestion/service.py
app/ingestion/pipeline.py
app/ingestion/ticket_loader.py
tests/test_chunking.py
tests/test_ingestion_preview_contract.py
tests/test_app.py
docs/integration-contracts.md
docs/knowledge-authoring.md
```

## Implementacao sugerida

Passos recomendados:

- definir uma funcao unica para normalizar texto antes do split
- garantir que `chunk_size` e `chunk_overlap` sejam configuraveis sem surpresa
- manter `chunk_index` estavel para o mesmo documento
- descartar texto vazio antes e depois do split
- calcular `content_hash` em camada preparatoria, mesmo sem persistir ainda
- manter preview por payload e preview por dominio com saidas compativeis

## Conteudo proibido

Esta frente nao deve:

- persistir chunks parcialmente sem contrato de banco fechado
- chamar provider de embedding dentro do preview
- esconder arquivos problematicos em vez de reportar erro claro
- misturar conteudo de dominios diferentes no mesmo resultado
- aceitar payload livre sem limites server-side

## Testes a adicionar ou revisar

Casos minimos:

- texto curto gera um chunk
- texto longo gera multiplos chunks ordenados
- texto vazio ou branco e rejeitado no contrato HTTP
- chunks preservam `source`, `title` e `chunk_index`
- preview por payload respeita limite de documentos e tamanho
- preview por dominio nao mistura outro dominio
- reprocessar mesmo texto gera hash e indices estaveis

## Validacao

Durante a frente:

```powershell
python -m pytest tests/test_chunking.py tests/test_ingestion_preview_contract.py
```

Validacao completa antes de commit:

```powershell
python -m compileall app scripts tests
python -m pytest
python -m app.evals.run_domain_eval suporte-vps-whatsapp
```

## Criterios de pronto

- Ha uma regra unica e testada para chunking.
- Preview local e preview por payload geram shape compativel.
- Chunks vazios ou duplicados nao entram no resultado.
- `source`, `title` e `chunk_index` permanecem estaveis.
- A frente de banco consegue consumir o output sem inferir regra escondida.
- Mudancas de contrato estao documentadas.

## Estimativa

- Mapear caminhos de ingestao atuais: 30 a 45 minutos
- Consolidar chunking e modelos: 1 a 2 horas
- Testar preview e regressao: 45 a 90 minutos

Total esperado: 2,25 a 4 horas.
