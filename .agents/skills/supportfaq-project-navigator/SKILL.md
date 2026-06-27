---
name: supportfaq-project-navigator
description: Use when an AI agent needs to understand, navigate, plan, or modify the supportFAQagent project without guessing architecture. Helps choose the right docs, folders, tests, and ownership boundaries for changes involving product positioning, FastAPI, domains, ingestion, GitHub loaders, retrieval, LLM, evals, Meta WhatsApp, Hermes, PostgreSQL/pgvector, VPS, observability, dependency management, or knowledge base content.
---

# supportFAQagent Project Navigator

## O que esta skill faz

Skill que ajuda o agente a navegar no projeto sem alucinar arquitetura. Ela orienta a leitura do `README.md`, `CONTRIBUTING.md` e dos docs certos para cada tipo de mudanca, indicando pastas, responsabilidades, testes e riscos de atropelar outra frente.

Use this skill before changing project structure, code, docs, domains, integrations, or knowledge content.

Goal: understand the project from repository sources, read only the needed docs, and avoid hallucinating architecture.

Also preserve the product positioning in `docs/product-positioning.md`: commercial but technical, operationally safe, traceable, and honest about MVP limits.

## First Step

Always start with:

1. Read `README.md`.
2. Read `docs/product-positioning.md` when the task touches README, docs, PR text, public positioning, onboarding, or agent instructions.
3. Read `CONTRIBUTING.md`.
4. Identify the change area.
5. Read only the docs needed for that area.

Do not load every doc by default.

## Area Map

Use this map to decide what to read.

| Change area | Read before editing | Likely folders |
| --- | --- | --- |
| Product positioning, README, public docs, PR narrative, agent instructions | `docs/product-positioning.md`, `README.md`, `docs/agent-skills.md` | `README.md`, `docs/`, `.agents/skills/` |
| Architecture or module boundaries | `docs/architecture.md`, `docs/technical-implementation-plan.md`, `docs/navigation.md` | `app/`, `docs/` |
| API contracts | `docs/integration-contracts.md`, `docs/observability.md` | `app/api/routes/`, `app/api/schemas/`, `app/feedback/`, `tests/` |
| Domain behavior | `docs/domain-contract.md`, `docs/navigation.md` | `domains/<domain>/domain.yaml`, `app/domain_engine/` |
| Knowledge base or FAQs | `docs/knowledge-authoring.md`, `docs/domain-evals.md` | `domains/<domain>/knowledge/`, `domains/<domain>/evals/` |
| Evals or calibration | `docs/domain-evals.md`, `docs/knowledge-authoring.md` | `app/evals/`, `domains/<domain>/evals/`, `tests/` |
| Ingestion | `docs/integration-contracts.md`, `docs/technical-implementation-plan.md` | `app/ingestion/`, `app/api/routes/ingestion.py`, `app/api/schemas/ingestion.py` |
| GitHub document loader or external source loading | `docs/knowledge-authoring.md`, `docs/technical-implementation-plan.md`, `docs/navigation.md` | `app/ingestion/github_loader.py`, `scripts/fetch_github_document.py`, `tests/test_github_loader.py` |
| Retrieval or vector store | `docs/architecture.md`, `docs/technical-implementation-plan.md` | `app/retrieval/`, `app/orchestration/` |
| LLM/provider/prompt | `docs/technical-implementation-plan.md`, `docs/domain-contract.md` | `app/llm/`, `app/orchestration/`, `domains/<domain>/prompts/` |
| Handoff or escalation | `docs/domain-contract.md`, `docs/integration-contracts.md`, `docs/domain-evals.md` | `app/handoff/`, `app/orchestration/`, `domains/<domain>/domain.yaml`, `tests/` |
| Observability/logging | `docs/observability.md`, `docs/technical-implementation-plan.md` | `app/core/`, `app/main.py`, route files |
| Security or public surface hardening | `SECURITY.md`, `docs/security/`, `docs/observability.md`, `docs/code-standards.md` | `app/core/`, `app/api/`, `tests/security/`, `.github/workflows/` |
| Meta WhatsApp, Hermes or external transport integration | `docs/integration-contracts.md`, `docs/observability.md`, `docs/technical-implementation-plan.md` | docs first; do not move intelligence into any external transport |
| PostgreSQL/pgvector | `docs/technical-implementation-plan.md`, `docs/architecture.md`, `docs/runbooks/pgvector-promotion-checklist.md` | `app/db/`, `app/retrieval/`, `app/ingestion/pgvector_writer.py`, `migrations/`, `scripts/ingest_domain_pgvector.py`; coordinate with database owner |
| VPS/deploy/runtime | `docs/environments.md`, `docs/technical-implementation-plan.md`, `docs/observability.md`, `docs/runbooks/` | `scripts/runtime_preflight.ps1`, `scripts/staging_smoke.py`, config/docs; coordinate with infrastructure owner |
| Dependency management or security audit | `pyproject.toml`, `CONTRIBUTING.md`, `.github/workflows/security.yml` | `pyproject.toml`, `.github/workflows/`, docs that mention install commands |
| Local chat UI or static assets | `README.md`, `docs/environments.md`, `docs/technical-implementation-plan.md` | `app/static/`, `app/main.py`, `app/core/config.py` |

## Ownership Boundaries

- Renan: architecture, orchestration, tests, security, contracts, quality,
  docs, PostgreSQL, pgvector and persistence.
- Juliano: VPS, deploy, runtime environment, networking, logs, secrets,
  restore, external connectivity and LangChain utilities when needed. Legacy
  Evolution work is operational context, not the active MVP path.

If a task touches another person's primary area, prefer creating a contract, doc, adapter, or test seam instead of implementing their full responsibility.

## Project Rules

- Keep the core reusable across domains.
- Put domain-specific behavior in `domains/`, not hardcoded in `app/`.
- Routes should validate and orchestrate, not hold business logic.
- Prefer small adapters and interfaces over heavy framework coupling.
- Keep Meta, Hermes and any external transport outside the
  intelligence core.
- Treat PostgreSQL + pgvector as the planned production vector store.
- Treat Chroma as local/prototype unless the team explicitly decides otherwise.
- Treat `pyproject.toml` as the only dependency source of truth; do not create parallel dependency lists.
- Use the official GitHub Contents API for GitHub document ingestion; do not scrape GitHub HTML.
- Keep public communication commercial-technical: explain business value, traceability, safe fallback, and human handoff without promising full autonomy.
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
- Any Python module change: `python -m compileall app tests scripts`
- Domain, prompt, retrieval, handoff, or knowledge change: `python -m app.evals.run_domain_eval suporte-vps-whatsapp`
- API contract change: add/update endpoint tests and update `docs/integration-contracts.md`
- Knowledge article change: update eval references when expected behavior changes
- Dependency change: `python -m pip_audit .`, `python -m pip check`, and extra dry-runs when optional extras change

## Output Style

When reporting a plan or summary, include:

- Area touched.
- Docs read.
- Files likely affected.
- Tests/evals required.
- Ownership risks or "no ownership conflict found".
