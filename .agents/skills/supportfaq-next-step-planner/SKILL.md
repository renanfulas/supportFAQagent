---
name: supportfaq-next-step-planner
description: Use when someone asks what to do next in the supportFAQagent project, wants to start a task, validate whether an intended change is aligned with the technical plan, or avoid overlapping with another contributor's responsibility. This skill checks main/current state, recent commits or PRs, the technical plan, and then asks only what the person intends to change and their name/responsibility before recommending the safest next step.
---

# supportFAQagent Next Step Planner

## O que esta skill faz

Skill que ajuda a decidir "o que fazer agora" sem atropelar o plano tecnico ou outra frente do time. Ela verifica a `main`, ultimos commits/PRs e docs do plano, pergunta apenas o que a pessoa pretende mexer e qual o responsavel, e entao sugere o menor proximo passo seguro.

Use this skill when a contributor asks:

- "O que eu faco agora?"
- "Qual proximo passo?"
- "Posso mexer nisso?"
- "Isso atropela alguem?"
- "Estou pensando em implementar X."

Goal: act as a lightweight technical coordinator. Do not implement first. First align intent, responsibility, plan, and next safe action.

## Core Rule

Ask only these two questions when the user's intent or identity is missing:

```text
O que voce pretende implementar ou mexer?
Qual seu nome/responsavel pela frente?
```

If both are already clear from the conversation, do not ask again.

## Required Context Check

Before recommending a next step, inspect the current project state.

Preferred commands:

```bash
git status --short --branch
git log --oneline --decorate -15
```

If safe and useful, update local main first:

```bash
git switch main
git pull --ff-only
```

Do not force reset or discard user changes.

## Required Docs

Read these first:

1. `README.md`
2. `docs/technical-implementation-plan.md`
3. `docs/mvp-plan.md`
4. `docs/navigation.md`

Then read only the task-specific docs:

| Intended area | Additional docs |
| --- | --- |
| API/n8n/contracts | `docs/integration-contracts.md`, `docs/observability.md` |
| Domain config | `docs/domain-contract.md` |
| Knowledge/RAG content | `docs/knowledge-authoring.md`, `docs/domain-evals.md` |
| Evals/calibration | `docs/domain-evals.md` |
| Observability/security | `docs/observability.md`, `docs/code-standards.md` |
| PostgreSQL/pgvector | `docs/technical-implementation-plan.md` SQL sections |
| LangChain/splitters/loaders | `docs/technical-implementation-plan.md`, ingestion sections |
| Contribution/commit/PR | `CONTRIBUTING.md`, `.agents/skills/supportfaq-git-flow/SKILL.md` |

## Responsibility Map

Use this map to detect overlap:

| Person | Primary responsibility |
| --- | --- |
| Silotto - TekZoom HG | VPS, deploy, environment, networking, logs, runtime operation |
| Alexandre Madeira | n8n, PostgreSQL, pgvector, persistence, workflows, integrations |
| Juliano Barreto | LangChain utilities, splitter, loaders, RAG support without overcoupling |
| Renan | Architecture, orchestration, tests, security, contracts, quality, docs, coordination |

If the intended work crosses another person's area, recommend one of:

- create/adjust a contract instead of implementing their full task
- open a small preparatory PR
- wait for dependency
- coordinate with that owner before coding

## Planning Output

After context + intent + name are known, respond with:

```md
## Status atual

Resumo curto do que a main ja tem relacionado a essa area.

## Alinhamento com o plano

Se esta dentro do plano, adiantado demais, bloqueado ou dependente de outra frente.

## Risco de atropelo

Baixo/medio/alto e por que.

## Proximo passo seguro

Menor tarefa implementavel agora.

## Docs e arquivos para ler

Lista curta.

## Validacao esperada

Testes, evals ou checks que devem rodar.
```

Keep the answer practical. Do not write a long architecture essay unless asked.

## Decision Heuristics

- If the task is about contracts, tests, docs, evals, safety, or orchestration, Renan can usually proceed.
- If the task requires tables, migrations, pgvector queries, persistence, or workflow storage, involve Alexandre.
- If the task changes LangChain dependency strategy, splitter behavior, or loaders, involve Juliano.
- If the task assumes deploy, VPS logs, TLS, reverse proxy, environment variables, or runtime networking, involve Silotto.
- If the task touches public exposure, security, secrets, PII, or logs, require hardening and tests.

## What Not To Do

- Do not implement before asking intent and name when missing.
- Do not recommend rewriting the architecture from scratch.
- Do not move intelligence rules into n8n.
- Do not make Chroma the production source of truth unless the team explicitly decides.
- Do not bypass pgvector ownership by creating a parallel production vector store.
- Do not tell someone to edit files before pointing them to the relevant docs.

## Hand-off To Other Skills

Use with:

- `supportfaq-project-navigator` after the next step is chosen and before implementation.
- `supportfaq-git-flow` before commit, push, or PR.
