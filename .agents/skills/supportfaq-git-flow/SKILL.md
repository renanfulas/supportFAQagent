---
name: supportfaq-git-flow
description: Use when an AI agent or contributor needs to prepare tests, review changes, commit, push, or write a pull request for the supportFAQagent project. Enforces the repository's lightweight contribution flow, validation commands, scoped commits, and PR summaries based on CONTRIBUTING.md.
---

# supportFAQagent Git Flow

## O que esta skill faz

Skill que facilita testes, commit, push e descricao de PR. Ela orienta o agente a ler o fluxo de contribuicao, revisar `git status` e `git diff`, confirmar o escopo das mudancas, rodar validacoes e montar um template de PR claro.

Use this skill before committing, pushing, or opening a PR.

Goal: keep history readable, validate changes before sharing, and produce useful PR descriptions without bureaucracy.

## Before Commit

1. Read `CONTRIBUTING.md`.
2. Run `git status --short --branch`.
3. Run `git diff --stat`.
4. Confirm the change has one clear scope.
5. Check if docs or evals must be updated.
6. If the change touches public docs, README, PR narrative, or agent instructions, check `docs/product-positioning.md`.

Do not commit unrelated changes.

## Test First

Run validations before commit whenever possible.

Default validation:

```bash
python -m pytest
python -m compileall app tests scripts
```

Also run evals when the change touches:

- domain behavior
- knowledge base
- prompt building
- retrieval
- handoff
- LLM response behavior

Also run dependency/security checks when the change touches `pyproject.toml`, install docs, or audit workflows:

```bash
python -m pip check
python -m pip_audit .
```

If optional extras change, also validate installation and audit of the affected
extra, for example:

```bash
python -m pip install --dry-run -e ".[chroma]"
```

Command:

```bash
python -m app.evals.run_domain_eval suporte-vps-whatsapp
```

## Unit Test Guidance

Add or update tests before commit when behavior changes.

Use this quick map:

| Change type | Expected test |
| --- | --- |
| API schema/route | endpoint test with status code and payload |
| Domain loader/config | loader or domain contract test |
| Ingestion | preview/chunking test |
| GitHub document loader | loader unit test without network plus script/help validation when practical |
| Retrieval | adapter/service test |
| Observability | request id, log field, error contract test |
| Privacy/security | non-leakage or validation test |
| Knowledge/prompt/handoff | domain eval update |
| Dependency management | `pip check`, `pip_audit .`, and extra dry-runs for changed extras |

Docs-only changes usually do not need new unit tests, but still run the default validation if the repo is available.

## Commit

Commit message style:

- Use imperative mood.
- Keep it short and specific.
- Mention the intent, not every file.

Examples:

```bash
git commit -m "Add ingestion preview contract"
git commit -m "Harden request observability privacy"
git commit -m "Improve support knowledge baseline"
```

Avoid:

- `fix`
- `updates`
- `misc changes`
- mixing refactor, feature, docs, and unrelated cleanup when avoidable

## Push

Use the current branch unless the user asks otherwise.

```bash
git push -u origin <branch-name>
```

Prefer branch names with a clear prefix and topic:

```text
codex/short-topic
```

## PR Description Template

Use this format:

```md
## O que foi feito

Resumo curto da entrega e por que ela existe.

## Principais mudanças

- Mudança principal 1.
- Mudança principal 2.
- Mudança principal 3.

## Validação

- `python -m pytest`
- `python -m compileall app tests`
- `python -m app.evals.run_domain_eval suporte-vps-whatsapp` quando aplicavel
```

For README, docs, or PR narrative changes, include the product or operational impact and avoid promises that conflict with `docs/product-positioning.md`.

## Final Response After Push

Include:

- commit done
- branch name
- PR URL
- PR description
- validation commands that passed

If tests were not run, say exactly why.

## Atualizar o estado dos planos (antes de finalizar)

Ao terminar uma fase ou frente, **antes do commit/PR**, atualize a documentação
de estado para o time nunca se perder:

1. Plano da frente em `docs/quality-plans/<frente>.md`: marque o que foi
   entregue e o que ainda falta. Plano totalmente encerrado vai para
   `docs/archive/`.
2. `docs/project-map.md`: ajuste o status da frente (✅ feito / 🟡 em andamento
   / ⬜ falta) e a nota da linha correspondente.
3. `docs/documentation-status.md`: só quando mudar status, ownership, contrato
   HTTP, migration ou operação.

Registre de forma concreta o que mudou. Exemplo:

> Frente handoff: Fase 2 concluída. Implementado: ticket no support inbox
> (`ENABLE_SUPPORT_INBOX`) e notificação WhatsApp ao time. Falta: enriquecimento
> de push (Fase B) reusando `build_case_context`.

Assim, quando a próxima frente começar, o agente já fica situado: lê o
`project-map.md`, vai ao plano da frente e sabe exatamente onde parou.

Regra de pastas: documento novo entra na pasta certa da taxonomia (ver
`docs/project-map.md` e `docs/navigation.md`); não deixe docs soltos na raiz. A
guarda `tests/test_docs_links.py` falha se um link de doc quebrar — rode-a
quando mover ou renomear documentos.
