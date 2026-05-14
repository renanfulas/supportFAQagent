# Plano tecnico - Qualidade de ingestao e chunking

## Objetivo

Manter a ingestao de artigos, FAQs e conteudo curado em chunks previsiveis,
revisaveis por preview e prontos para uma futura camada de persistencia e
embedding, sem acoplar o core ao banco nem expor tipos do LangChain como
contrato publico do projeto.

Esta frente pode evoluir em paralelo a `pgvector`, porque seu papel atual e
estabilizar o shape dos documentos e chunks antes da persistencia real.

## Estado atual alinhado ao repositorio

O projeto ja possui:

- `GET /ingestion/{domain_name}/preview`, que le arquivos locais em
  `domains/<domain>/knowledge` a partir das fontes declaradas no `domain.yaml`.
- `POST /ingestion/preview`, protegido por `X-API-Key`, que recebe payload JSON
  livre, valida limites e retorna chunks para revisao antes de persistir.
- `IngestionService`, que carrega arquivos `.md` e `.txt`, deriva titulo pelo
  nome do arquivo e converte `KnowledgeDocument` em `KnowledgeChunk`.
- `split_text` e `split_documents_to_dicts` em `app/ingestion/chunking.py`, que
  usam `RecursiveCharacterTextSplitter` quando disponivel, mas retornam
  dicionarios puros.
- fallback simples de split quando a dependencia de LangChain nao esta
  disponivel.
- `pipeline.py` para CSV de chamados usando `ticket_loader.py` e `ChromaStore`,
  ainda como caminho auxiliar/prototipo, nao como ingestao persistente oficial.
- testes cobrindo chunking compartilhado, preview por payload, fallback de
  `source`, rejeicao de conteudo em branco e preview local por dominio.

Ainda nao existe nesta frente:

- persistencia de artigos, chunks ou hashes em PostgreSQL.
- geracao de embeddings no preview.
- IDs persistidos de chunk no contrato HTTP.
- `domain`, `content_hash`, `metadata` ou `token_estimate` no modelo publico
  `KnowledgeChunk` retornado pelos previews.
- configuracao por dominio para `chunk_overlap`; hoje o preview por payload
  configura `chunk_size` e o overlap padrao vem do splitter.

## Problema observado

O risco principal e criar caminhos paralelos de chunking com resultados
divergentes para o mesmo conteudo. Hoje artigos locais e payloads do preview ja
passam por `IngestionService.chunk_documents`, enquanto CSV de chamados passa
por `split_documents_to_dicts` no pipeline auxiliar.

Lacunas principais:

- manter `split_text`, `split_documents_to_dicts` e `IngestionService` com
  regras compativeis.
- descartar ou evitar chunks vazios de forma previsivel em todos os caminhos.
- preservar `source`, `title` e `chunk_index` no contrato HTTP atual.
- decidir quando promover `metadata`, `token_estimate` e `content_hash` para
  modelos internos ou contratos futuros.
- deixar claro que preview nao persiste, nao gera embedding e nao cria IDs
  definitivos.

## Escopo

Entram nesta frente quando houver trabalho de codigo:

- revisar `app/ingestion/chunking.py`.
- revisar `app/ingestion/models.py`.
- revisar `app/ingestion/service.py`.
- revisar `app/ingestion/pipeline.py`.
- revisar `app/ingestion/ticket_loader.py`.
- ajustar `app/api/routes/ingestion.py` e `app/api/schemas/ingestion.py` apenas
  quando o contrato de preview precisar mudar.
- atualizar testes de chunking e preview.
- atualizar `docs/integration-contracts.md` somente se o shape HTTP mudar.

Ficam fora desta frente:

- escrever em PostgreSQL.
- gerar embeddings.
- executar jobs assincronos de ingestao.
- criar painel de curadoria.
- ingerir massa historica sem curadoria.
- tornar `Document` do LangChain tipo central do projeto.
- substituir o retrieval lexical ativo do `/chat`.

## Contrato atual de preview

`POST /ingestion/preview` aceita:

- `domain`: obrigatorio, sem branco puro, maximo 80 caracteres.
- `documents`: de 1 a 20 documentos.
- `documents[].title`: obrigatorio, sem branco puro, maximo 160 caracteres.
- `documents[].content`: obrigatorio, sem branco puro, maximo 20000 caracteres.
- `documents[].source`: opcional, maximo 240 caracteres; quando vazio, vira
  `payload:<indice>`.
- `chunk_size`: opcional, minimo 200, maximo 2000, padrao 800.

`GET /ingestion/{domain_name}/preview` aceita um dominio no path, carrega os
arquivos locais permitidos e retorna uma previa sem exigir `X-API-Key` no estado
atual do MVP.

Ambos retornam os campos basicos:

- `request_id` quando aplicavel.
- `domain`.
- `document_count`.
- `chunk_count`.
- `sample_chunks`.
- `chunks` com `source`, `title`, `text` e `chunk_index` quando o endpoint
  inclui a lista completa.

## Contrato interno desejado para chunks

Todo chunk utilizavel pelo RAG deve preservar, no minimo:

- `domain` quando o chunk sair da camada de preview e entrar em persistencia ou
  retrieval multi-dominio.
- `source`.
- `title`.
- `text` ou `chunk_text`, conforme a camada.
- `chunk_index`.
- metadados simples e serializaveis quando existirem.

No futuro, a persistencia pode adicionar IDs, hash, timestamps,
`token_estimate` e metadados ricos, mas nao deve quebrar os campos basicos ja
documentados em `docs/integration-contracts.md`.

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

- manter `split_text` como regra compartilhada para documentos locais e preview
  por payload.
- manter `split_documents_to_dicts` compativel com o mesmo criterio de tamanho,
  overlap seguro, indice e metadados.
- normalizar texto antes do split sem apagar estrutura util de artigos quando
  isso prejudicar recuperacao.
- garantir que texto vazio ou branco nao produza chunks silenciosos.
- manter `chunk_index` estavel dentro de cada documento.
- avaliar `content_hash` como campo preparatorio interno antes de expor em HTTP.
- manter preview por payload e preview por dominio com saidas compativeis.

## Conteudo proibido

Esta frente nao deve:

- persistir chunks parcialmente sem contrato de banco fechado.
- chamar provider de embedding dentro do preview.
- esconder arquivos problematicos em vez de reportar comportamento claro.
- misturar conteudo de dominios diferentes no mesmo resultado.
- aceitar payload livre sem limites server-side.
- vazar PII, tokens, senhas ou chaves vindos de artigos ou chamados.

## Testes a adicionar ou revisar

Casos minimos:

- texto curto gera um chunk.
- texto longo gera multiplos chunks ordenados.
- texto vazio ou branco e rejeitado no contrato HTTP.
- chunks preservam `source`, `title` e `chunk_index`.
- preview por payload respeita limite de documentos e tamanho.
- preview por payload retorna `request_id`.
- preview por payload retorna 404 para dominio inexistente.
- preview por dominio nao mistura outro dominio.
- fallback sem LangChain continua retornando dicionarios puros.
- reprocessar mesmo texto gera indices estaveis; hash deve ser testado quando
  for implementado.

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

- Ha uma regra compartilhada e testada para chunking.
- Preview local e preview por payload geram shape compativel.
- Chunks vazios nao entram no resultado.
- `source`, `title` e `chunk_index` permanecem estaveis.
- O contrato HTTP continua alinhado com `docs/integration-contracts.md`.
- A frente de banco consegue consumir o output sem inferir regra escondida.
- Mudancas de contrato estao documentadas antes de consumidores externos
  dependerem delas.

## Estimativa

- Mapear caminhos de ingestao atuais: 30 a 45 minutos.
- Consolidar chunking e modelos: 1 a 2 horas.
- Testar preview e regressao: 45 a 90 minutos.

Total esperado: 2,25 a 4 horas.
