# Archive Da Documentacao

Esta pasta preserva planos concluidos, relatorios substituidos e roadmaps
historicos. Nenhum documento daqui deve ser usado como fonte operacional atual
sem confirmar seu substituto ativo.

## Regras

- documentos arquivados continuam versionados para preservar decisoes e
  evidencias;
- runbooks executaveis ativos permanecem fora do archive;
- um plano entra aqui quando nao possui tarefa executavel restante;
- um relatorio entra aqui quando uma evidencia posterior o substitui;
- links ativos devem apontar primeiro para a fonte atual, nao para o archive.

## Planos De Implementacao Concluidos

| Documento arquivado | Motivo | Fonte atual |
| --- | --- | --- |
| [Chat web V0](implementation-plans/web-chat-v0-implementation-plan.md) | V0 incorporada ao produto | [`docs/quality-plans/web-chat-evolution-plan.md`](../quality-plans/web-chat-evolution-plan.md) |
| [Retrieval vetorial](implementation-plans/vector-retrieval-quality-plan.md) | adapter e gate incorporados ao MVP | [`docs/MVP/technical-implementation-plan.md`](../MVP/technical-implementation-plan.md) |
| [Chat web V1B (ponte OTP n8n/Evolution)](implementation-plans/web-chat-v1b-postgres-n8n-plan.md) | `n8n` removido do projeto; ponte superseded por Meta WhatsApp nativo | [`docs/quality-plans/meta-whatsapp-native-integration-plan.md`](../quality-plans/meta-whatsapp-native-integration-plan.md) |
| [Roteamento de dominio pegajoso (sticky)](implementation-plans/whatsapp-sticky-domain-routing-plan.md) | seam + adapter duravel `PgSessionDomainStore` entregues e validados em CI, sem tarefa executavel restante | [`docs/project-map.md`](../project-map.md) (linha da frente), `tests/test_domain_router.py`, `tests/integration/test_session_domain_store_postgres.py` |

## Runbooks De Tecnologia Removida

| Documento arquivado | Motivo | Fonte atual |
| --- | --- | --- |
| [Subir n8n em Docker na VPS](runbooks/n8n-vps-docker-deploy.md) | `n8n` removido; assets `deploy/n8n/` excluidos do repo | [`docs/quality-plans/meta-whatsapp-native-integration-plan.md`](../quality-plans/meta-whatsapp-native-integration-plan.md) |
| [Contrato n8n/WhatsApp para `/chat`](runbooks/n8n-whatsapp-chat-contract.md) | `n8n` removido; contrato `/chat` vive na fonte atual | [`docs/architecture/integration-contracts.md`](../architecture/integration-contracts.md) |
| [Workflows n8n versionados](runbooks/n8n-versioned-workflows.md) | `n8n` removido; templates `deploy/n8n/workflows/` excluidos | [`docs/quality-plans/meta-whatsapp-native-integration-plan.md`](../quality-plans/meta-whatsapp-native-integration-plan.md) |

## Relatorios Historicos

| Documento arquivado | Motivo | Fonte atual |
| --- | --- | --- |
| [Validacao inicial de staging](historical-reports/staging-runtime-validation-report.md) | evidencia de maio substituida pela Fase 0 | [`docs/runbooks/phase0-staging-promotion-evidence.md`](../runbooks/phase0-staging-promotion-evidence.md) |
| [Revisao da base de conhecimento - 2026-05-17](historical-reports/knowledge-base-review-2026-05-17.md) | premissa do documento ("aguardando relatorio anonimo da HostGator") ja superada; a base cresceu de 8 para 13 fontes desde entao | [`docs/architecture/knowledge-authoring.md`](../architecture/knowledge-authoring.md), [`docs/architecture/domain-evals.md`](../architecture/domain-evals.md) |

## Roadmaps Historicos De Seguranca

| Documento arquivado | Motivo | Fonte atual |
| --- | --- | --- |
| [Tracking inicial](security-roadmaps/implementation-tracking.md) | ownership e status originais substituidos | [`docs/quality-plans/phase0-operational-risk-reduction.md`](../quality-plans/phase0-operational-risk-reduction.md) |
| [Guia Git inicial](security-roadmaps/git-commit-guide.md) | fluxo substituido pela skill atual | [`.agents/skills/supportfaq-git-flow/SKILL.md`](../../.agents/skills/supportfaq-git-flow/SKILL.md) |

## Fonte De Verdade

Consulte [`docs/documentation-status.md`](../documentation-status.md) antes de
usar qualquer documento arquivado.
