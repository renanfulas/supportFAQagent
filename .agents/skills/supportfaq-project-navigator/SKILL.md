---
name: supportfaq-project-navigator
description: Use when an AI agent needs to understand, navigate, plan, or modify the supportFAQagent project without guessing architecture. Helps choose the right docs, folders, tests, and ownership boundaries for changes involving FastAPI, domains, ingestion, retrieval, LLM, evals, n8n, PostgreSQL/pgvector, VPS, observability, or knowledge base content.
---

# supportFAQagent Project Navigator

## O que esta skill faz

Skill que ajuda o agente a navegar no projeto sem alucinar arquitetura. Ela orienta a leitura do `README.md`, `CONTRIBUTING.md` e dos docs certos para cada tipo de mudanca, indicando pastas, responsabilidades, testes e riscos de atropelar outra frente.

Use this skill before changing project structure, code, docs, domains, integrations, or knowledge content.

Goal: understand the project from repository sources, read only the needed docs, and avoid hallucinating architecture.

## First Step

Always start with:

1. Read `README.md`.
2. Read `CONTRIBUTING.md`.
3. Identify the change area.
4. Read only the docs needed for that area.

Do not load every doc by default.

## Area Map

Use this map to decide what to read.

| Change area | Read before editing | Likely folders |
| --- | --- | --- |
| Architecture or module boundaries | `docs/architecture.md`, `docs/technical-implementation-plan.md` | `app/`, `docs/` |
| API contracts | `docs/integration-contracts.md`, `docs/observability.md` | `app/api/routes/`, `app/api/schemas/`, `tests/` |
| Domain behavior | `docs/domain-contract.md`, `docs/navigation.md` | `domains/<domain>/domain.yaml`, `app/domain_engine/` |
| Knowledge base or FAQs | `docs/knowledge-authoring.md`, `docs/domain-evals.md` | `domains/<domain>/knowledge/`, `domains/<domain>/evals/` |
| Evals or calibration | `docs/domain-evals.md`, `docs/knowledge-authoring.md` | `app/evals/`, `domains/<domain>/evals/`, `tests/` |
| Ingestion | `docs/integration-contracts.md`, `docs/technical-implementation-plan.md` | `app/ingestion/`, `app/api/routes/ingestion.py`, `app/api/schemas/ingestion.py` |
| Retrieval or vector store | `docs/architecture.md`, `docs/technical-implementation-plan.md` | `app/retrieval/`, `app/orchestration/` |
| LLM/provider/prompt | `docs/technical-implementation-plan.md`, `docs/domain-contract.md` | `app/llm/`, `app/orchestration/`, `domains/<domain>/prompts/` |
| Observability/logging | `docs/observability.md`, `docs/technical-implementation-plan.md` | `app/core/`, `app/main.py`, route files |
| n8n integration | `docs/integration-contracts.md`, `docs/observability.md`, `docs/technical-implementation-plan.md` | docs first; do not move intelligence into n8n |
| PostgreSQL/pgvector | `docs/technical-implementation-plan.md`, `docs/architecture.md` | `app/db/`, `app/retrieval/`; coordinate with database owner |
| VPS/deploy | `docs/technical-implementation-plan.md`, `docs/observability.md` | config/docs; coordinate with infrastructure owner |

## Ownership Boundaries

- Renan: architecture, orchestration, tests, security, contracts, quality, docs.
- Alexandre: n8n, PostgreSQL, pgvector, persistence, workflows.
- Juliano: LangChain utilities, splitter/loaders, RAG support without overcoupling.
- Silotto: VPS, deploy, runtime environment, networking, logs.

If a task touches another person's primary area, prefer creating a contract, doc, adapter, or test seam instead of implementing their full responsibility.

## Project Rules

- Keep the core reusable across domains.
- Put domain-specific behavior in `domains/`, not hardcoded in `app/`.
- Routes should validate and orchestrate, not hold business logic.
- Prefer small adapters and interfaces over heavy framework coupling.
- Keep n8n as automation/orchestration outside the intelligence core.
- Treat PostgreSQL + pgvector as the planned production vector store.
- Treat Chroma as local/prototype unless the team explicitly decides otherwise.
- Do not log raw PII, tokens, secrets, prompts with sensitive data, or raw `session_id`.

## Before Editing

Answer these internally:

1. Is this shared core behavior or domain-specific behavior?
2. Which docs define the current contract?
3. Which owner/frente could be affected?
4. What test or eval should prove the change?
5. Does this require documentation updates?

## Validation Guidance

Choose validations by change type:

- Any code change: `python -m pytest`
- Any Python module change: `python -m compileall app tests`
- Domain, prompt, retrieval, handoff, or knowledge change: `python -m app.evals.run_domain_eval suporte-vps-whatsapp`
- API contract change: add/update endpoint tests and update `docs/integration-contracts.md`
- Knowledge article change: update eval references when expected behavior changes

## Output Style

When reporting a plan or summary, include:

- Area touched.
- Docs read.
- Files likely affected.
- Tests/evals required.
- Ownership risks or "no ownership conflict found".
