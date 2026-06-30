# Indice de redirecionamento de documentos

Os documentos abaixo foram movidos para pastas tematicas (ver
`docs/project-map.md` para a taxonomia). Esta tabela mapeia o **caminho antigo**
para o **caminho novo**.

Use-a quando encontrar um caminho antigo em PRs antigos, bookmarks, memoria de
agente ou comentarios externos. Os links e referencias dentro do repositorio ja
foram atualizados; este indice cobre o que vive **fora** do controle do repo.

E um auxilio de transicao: pode ser removido quando os caminhos antigos sairem
de circulacao. O teste `tests/test_docs_links.py::test_references_legacy_mapping`
garante que todo caminho novo existe e todo caminho antigo nao existe mais.

## Para `docs/architecture/`

| Caminho antigo | Caminho novo |
| --- | --- |
| `docs/architecture.md` | `docs/architecture/architecture.md` |
| `docs/framework-boundary.md` | `docs/architecture/framework-boundary.md` |
| `docs/domain-contract.md` | `docs/architecture/domain-contract.md` |
| `docs/domain-architecture-roadmap.md` | `docs/architecture/domain-architecture-roadmap.md` |
| `docs/integration-contracts.md` | `docs/architecture/integration-contracts.md` |
| `docs/observability.md` | `docs/architecture/observability.md` |
| `docs/code-standards.md` | `docs/architecture/code-standards.md` |
| `docs/conversation-archive-sink.md` | `docs/architecture/conversation-archive-sink.md` |
| `docs/cost-latency-profile.md` | `docs/architecture/cost-latency-profile.md` |
| `docs/knowledge-authoring.md` | `docs/architecture/knowledge-authoring.md` |
| `docs/domain-evals.md` | `docs/architecture/domain-evals.md` |

## Para `docs/setup/`

| Caminho antigo | Caminho novo |
| --- | --- |
| `docs/environments.md` | `docs/setup/environments.md` |
| `docs/runbooks/configuracaoVPS.md` | `docs/setup/configuracaoVPS.md` |
| `docs/runbooks/local-postgres-test-harness.md` | `docs/setup/local-postgres-test-harness.md` |
| `docs/runbooks/local-wsl1-pgvector-phase0.md` | `docs/setup/local-wsl1-pgvector-phase0.md` |

## Para `docs/MVP/`

| Caminho antigo | Caminho novo |
| --- | --- |
| `docs/mvp-plan.md` | `docs/MVP/mvp-plan.md` |
| `docs/technical-implementation-plan.md` | `docs/MVP/technical-implementation-plan.md` |

## Para `docs/quality-plans/`

| Caminho antigo | Caminho novo |
| --- | --- |
| `docs/web-chat-evolution-plan.md` | `docs/quality-plans/web-chat-evolution-plan.md` |
| `docs/web-chat-v1-whatsapp-otp-spec.md` | `docs/quality-plans/web-chat-v1-whatsapp-otp-spec.md` |

## Para `docs/archive/historical-reports/`

| Caminho antigo | Caminho novo |
| --- | --- |
| `docs/answer-quality-comparison.md` | `docs/archive/historical-reports/answer-quality-comparison.md` |
| `docs/runbooks/local-phase0-validation-report-2026-06-12.md` | `docs/archive/historical-reports/local-phase0-validation-report-2026-06-12.md` |
| `docs/runbooks/local-pgvector-baseline-report.md` | `docs/archive/historical-reports/local-pgvector-baseline-report.md` |
