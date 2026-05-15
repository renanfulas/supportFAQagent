# Politica de Seguranca - supportFAQagent

## Versao suportada

| Versao | Suporte de seguranca |
| --- | --- |
| `main` (MVP) | Ativa |
| branches de trabalho | Em desenvolvimento |

## Reportar uma vulnerabilidade

Nao abra uma Issue publica para reportar vulnerabilidades.

Se voce encontrou uma falha de seguranca neste projeto, entre em contato de forma privada:

- Abra um GitHub Security Advisory na aba Security do repositorio.
- Ou envie mensagem direta para o mantenedor principal: [@renanfulas](https://github.com/renanfulas).

### O que incluir no relatorio

- Descricao clara da vulnerabilidade.
- Passos para reproduzir.
- Impacto potencial.
- Sugestao de correcao, se tiver.

### O que esperar

- Confirmacao de recebimento em ate 48 horas.
- Avaliacao de severidade em ate 5 dias uteis.
- Correcao publicada em ate 30 dias para severidade alta ou critica, quando confirmada.

## Escopo deste projeto

Este repositorio cobre:

- API FastAPI (`app/`).
- Pipeline RAG e ingestao (`app/ingestion/`, `app/retrieval/`).
- Configuracao de dominios (`domains/`).
- Scripts operacionais (`scripts/`).
- Integracoes planejadas ou em evolucao documentadas no repositorio.

## Automacao atual

O repositorio passa a ter GitHub Actions para CI e checks basicos de seguranca:

- `.github/workflows/ci.yml` roda em pull requests e pushes para `main`, compila `app`, `tests` e `scripts`, e executa `pytest`.
- `.github/workflows/security.yml` roda em pull requests, pushes para `main` e semanalmente, com Gitleaks para secrets e `pip-audit` para dependencias Python.

Essas verificacoes reduzem risco, mas nao substituem revisao humana, rotacao de credenciais quando necessario, nem hardening do ambiente de producao.

## Praticas de seguranca do time

- Chaves de API, senhas, tokens e dados sensiveis nao devem ser commitados.
- O arquivo `.env` deve permanecer fora do versionamento.
- Pull Requests para `main` devem ser revisados antes do merge.
- Mudancas que afetem dados sensiveis, logs, credenciais, LLM, RAG ou integracoes externas devem explicar riscos e validacoes na PR.

## Creditos

Agradecemos a qualquer pessoa que reporte vulnerabilidades de forma responsavel. Contribuidores de seguranca podem ser reconhecidos com permissao.

supportFAQagent - Open Source patrocinado por HostGator
Mantenedor: Renan Junior | Comunidade: Alexandre Madeira, Juliano Barreto, Silotto
