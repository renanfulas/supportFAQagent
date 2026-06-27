# Perfil de custo e latencia por dominio

Documento que explica, com numeros reais e reproduziveis, por que o bot responde
rapido e custa pouco por request, e quanto isso muda ao subir para `pgvector`.
Complementa `docs/observability.md` (campos `total_ms`, `retrieval_ms`, `llm_ms`
emitidos em cada resposta) e `docs/runbooks/pgvector-promotion-checklist.md`.

Posicionamento: alinhado a `docs/product-positioning.md` — comercial-tecnico e
honesto sobre limites de MVP. Os numeros de latencia que o bot controla sao
baixos; a unica latencia relevante e o round-trip do modelo, e parte do custo
"baixo" vem de atalhos de seguranca, nao so do modelo barato.

## Como reproduzir

```bash
# Offline, deterministico, sem custo (provider mock; backend lexical):
python scripts/profile_cost_latency.py --markdown

# Cenario pgvector (inclui custo de embedding da query):
python scripts/profile_cost_latency.py --embedding-cost --markdown

# Latencia/tokens REAIS do LLM nos N primeiros casos elegiveis (GERA CUSTO):
python scripts/profile_cost_latency.py --live 3
```

O script ([scripts/profile_cost_latency.py](../scripts/profile_cost_latency.py))
roda a suite `evals/cases.yaml` de cada dominio como workload. Por padrao forca
provider `mock` e backend `lexical`: nao faz chamada de rede, nao gasta credito e
e deterministico. A saida agrega metricas e nunca inclui o texto das perguntas
(com `--per-case` mostra apenas `case_id` + metricas).

## O que e real x o que e estimado

| Metrica | Origem |
| --- | --- |
| `retrieval_ms` | **Real** — cronometra `RetrievalService.retrieve` (lexical). |
| `pipeline_overhead_ms` | **Real** — orquestracao completa com provider mock (retrieval + handoff + confidence + montagem do prompt). Nao inclui o round-trip do modelo. |
| `avg_input_tokens_per_llm_call` | **Real** — tokeniza o prompt efetivamente montado por `build_prompt`. |
| `llm_eligible_share` / `short_circuit_breakdown` | **Real** — fracao de casos que chega ao LLM x atalhos (checkout, bloqueio de seguranca, sem contexto). |
| `output_tokens` | **Assumido** (default 220) — ou **medido** em modo `--live`. |
| `cost_usd` | **Estimado** — tabela `MODEL_PRICES_USD_PER_1M` no script (referencia 2026-06; confirme a tabela vigente). |
| `live_llm_ms` | **Real**, apenas em `--live` — round-trip do modelo. |

Limitacoes assumidas: tokens sao contados com `tiktoken` quando disponivel, senao
por heuristica `chars/4` (boa para pt-BR, nao serve para faturamento exato); o
custo por request usa o orcamento de saida assumido e ignora cache de prompt.

## Resultado (medido em 2026-06-26, backend lexical)

| Dominio | Modelo | retrieval avg/p95 (ms) | overhead avg/p95 (ms) | tokens in/chamada | % req no LLM | USD/1k req |
| --- | --- | --- | --- | --- | --- | --- |
| `vendas` | gpt-4o-mini | 1.85 / 1.90 | 2.04 / 2.12 | ~2509 | 92% | ~$0.47 |
| `suporte-vps-whatsapp` | gpt-4o-mini | 2.91 / 2.95 | 2.30 / 3.13 | ~1506 | 65% | ~$0.23 |
| `suporte-hospedagem` | gpt-4o-mini | 3.02 / 3.04 | 3.18 / 3.25 | ~1811 | 94% | ~$0.38 |

Amostra real de round-trip do LLM (`--live`, gpt-4o-mini, prompts de 1.5k-2.5k
tokens de entrada): ~3,3 s em media, p95 ~4,9 s. Ou seja, **quase toda a latencia
percebida e o modelo**; tudo o que o bot controla (retrieval + orquestracao) soma
single-digit de milissegundos.

## Por que esta rapido e barato (com os numeros)

1. **Modelo barato e rapido.** Todos os dominios vivos usam `gpt-4o-mini` com
   `temperature=0.0` ([app/llm/wrapper.py](../app/llm/wrapper.py)). Custo por
   chamada estimado: ~US$ 0,0004-0,0005.
2. **Uma unica chamada de LLM por request.** Sem agent loop, sem re-ranking por
   LLM, sem cadeia multi-step ([app/orchestration/chat_flow.py](../app/orchestration/chat_flow.py)).
3. **Boa parte das requests nem chega ao modelo.** 6%-35% dos casos sao atalhos
   de custo zero de LLM: checkout deterministico, bloqueio de seguranca
   (`out_of_scope`, pedido de humano, prompt injection, pedido de segredo) e
   ausencia de contexto. `suporte-vps-whatsapp` e o mais defensivo (35% nao
   chamam o modelo), o que derruba o custo efetivo por request.
4. **Retrieval lexical e local.** Matching de palavras-chave em memoria, sem API
   de embeddings nem banco vetorial: ~2-3 ms por query, p95 < 3,3 ms
   ([app/retrieval/lexical_store.py](../app/retrieval/lexical_store.py)).
5. **Prompt enxuto.** Contexto limitado por `max_context_chunks`, historico de 4
   mensagens (`CONVERSATION_HISTORY_MESSAGES=8`) truncado a 2000 chars, e
   persistencia desligada por padrao — menos tokens de entrada.

## Impacto de subir para pgvector

O custo **por-token** de subir para pgvector e desprezivel: o embedding da query
(`text-embedding-3-small`, ~14 tokens/pergunta) adiciona ~US$ 0,0003 por 1k
requests. O que muda de verdade nao aparece nessa coluna:

- **Latencia:** `retrieval_ms` passa a incluir o embedding da query + round-trip
  ao Postgres, saindo dos ~2-3 ms locais para a faixa de rede/DB. Continua muito
  abaixo do round-trip do modelo, mas deixa de ser desprezivel.
- **Custo de ingestao (uma vez por atualizacao de base):** embedar todos os
  chunks de cada dominio — proporcional ao tamanho da base, nao ao trafego.
- **Infra e operacao:** Postgres + pgvector, `DATABASE_URL`, chave de embeddings,
  indices e manutencao (ownership Alexandre/Silotto).

Em troca, ganha-se qualidade de retrieval (sinonimos e parafrases que o lexical
erra). O trade-off honesto: hoje barato/rapido/raso; pgvector melhora a relevancia
ao custo de latencia de rede e infra.

## O que falta para aposentar o lexical

Estado atual: pgvector esta **implementado** (`PgVectorStore`,
`PostgresPgVectorSearchBackend`, `scripts/ingest_domain_pgvector.py`, suites
`pgvector_gate`/`pgvector_curated`) e **promovido como default do staging** desde
19/06/2026 via `.env`. O default de **codigo** segue `lexical`
([app/core/config.py](../app/core/config.py)) de proposito: e o caminho
zero-dependencia para local, CI e testes, e o plano de rollback operacional.

"Aposentar o lexical" nao e so trocar a flag — ele e a rede de seguranca. Para
torna-lo obsoleto faltam:

1. **pgvector disponivel em local/CI/testes** sem exigir `DATABASE_URL` + chave de
   embeddings de cada dev. Hoje os testes dependem do determinismo lexical; sem um
   pgvector local (ver `docs/runbooks/local-wsl1-pgvector-phase0.md`) ou um fake
   backend, remover o lexical quebra a suite.
2. **Todos os dominios roteados ingeridos no pgvector** com gate verde
   (`>=74/78`). Feito para `suporte-vps-whatsapp` e `vendas`; `suporte-hospedagem`
   e `suporte-vps` ainda na Fase 3 (ingestao pgvector pendente — ver
   `docs/domain-architecture-roadmap.md`).
3. **Custo/segredo de embeddings em CI** resolvido (CI hoje evita chave de
   propósito) ou substituido por um fake de embeddings deterministico.
4. **Plano de rollback alternativo.** Hoje o rollback E voltar para `lexical`;
   removendo-o, e preciso outra rede de seguranca antes.
5. **Decisao e ownership conjuntos.** pgvector/persistencia e Alexandre; runtime,
   rede e TLS e Silotto. Nao e mudanca Renan-only.

Caminho recomendado: promover pgvector a default de **codigo** quando 1-3
fecharem, mantendo um fallback `lexical`/fake para testes e rollback em vez de
remove-lo. Aposentadoria total do lexical so depois de 4-5 acordados.

## Validacao

```bash
python -m compileall scripts/profile_cost_latency.py
python scripts/profile_cost_latency.py --markdown
```

## Fronteiras de ownership

- Renan: este perfil, evals, contratos, criterios de promocao, qualidade.
- Alexandre: pgvector, ingestao, persistencia, indices.
- Silotto: runtime, rede, TLS, logs de operacao em staging/producao.
