---
name: supportfaq-git-flow
description: Use when an AI agent or contributor needs to prepare tests, review changes, commit, push, or write a pull request for the supportFAQagent project. Enforces the repository's lightweight contribution flow, validation commands, scoped commits, and PR summaries based on CONTRIBUTING.md.
---

# supportFAQagent Git Flow

Use this skill before committing, pushing, or opening a PR.

Goal: keep history readable, validate changes before sharing, and produce useful PR descriptions without bureaucracy.

## Before Commit

1. Read `CONTRIBUTING.md`.
2. Run `git status --short --branch`.
3. Run `git diff --stat`.
4. Confirm the change has one clear scope.
5. Check if docs or evals must be updated.

Do not commit unrelated changes.

## Test First

Run validations before commit whenever possible.

Default validation:

```bash
python -m pytest
python -m compileall app tests
```

Also run evals when the change touches:

- domain behavior
- knowledge base
- prompt building
- retrieval
- handoff
- LLM response behavior

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
| Retrieval | adapter/service test |
| Observability | request id, log field, error contract test |
| Privacy/security | non-leakage or validation test |
| Knowledge/prompt/handoff | domain eval update |

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

## Final Response After Push

Include:

- commit done
- branch name
- PR URL
- PR description
- validation commands that passed

If tests were not run, say exactly why.
