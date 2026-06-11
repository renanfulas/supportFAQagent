# Backlog De Calibracao Da Gate pgvector - 2026-06-11

## Objetivo

Registrar o saneamento offline dos quatro casos restantes da gate sem declarar
ganho pgvector antes de reingestao e execucao no ambiente apropriado.

## Casos Revisados

| Caso | Problema anterior | Ajuste offline |
| --- | --- | --- |
| `vps-020-erro-permission-denied-publickey` | assunto especifico misturado no artigo de timeout | novo FAQ `ssh-permission-denied-publickey.md` |
| `vps-049-disco-cheio` | referencia esperada apontava para indisponibilidade generica | referencia corrigida para `performance-recursos-vps.md` |
| `vps-051-site-lento` | faltava artigo focado e referencia era generica | novo FAQ `site-lento-vps.md` |
| `vps-091-banco-consome-disco` | referencia esperada apontava para indisponibilidade generica | referencia corrigida para `performance-recursos-vps.md` |

## Evidencia Offline

- os quatro casos possuem referencia recuperavel pelo retrieval lexical no
  top 5;
- `pgvector_gate.yaml` e `pgvector_curated.yaml` foram alteradas somente nesses
  quatro IDs;
- o gate deterministico esta em `tests/test_gate_backlog_retrieval.py`.

## Evidencia Ainda Necessaria

1. reingerir o dominio no PostgreSQL/pgvector;
2. rodar `pgvector_gate.yaml`;
3. comparar com o baseline anterior `74/78`;
4. rodar a curated para verificar efeitos colaterais;
5. somente entao atualizar o baseline oficial.

Esses casos permanecem como calibracao pendente enquanto a VPS e o laboratorio
pgvector real estiverem indisponiveis.
