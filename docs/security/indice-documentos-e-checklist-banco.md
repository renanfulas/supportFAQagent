# Indice de documentos de seguranca

Guia rapido para entender o papel de cada documento do pacote de seguranca e o checklist operacional mais imediato para a frente de banco.

## Indice geral

| Documento | Onde fica | Para quem e |
| --- | --- | --- |
| `SECURITY.md` | raiz do repositorio | comunidade e contribuidores externos |
| `docs/security/vps-security-plan.md` | `docs/security/` | time tecnico |
| `docs/security/llm-confinement.md` | `docs/security/` | arquitetura do agente |
| `docs/archive/security-roadmaps/implementation-tracking.md` | `docs/archive/security-roadmaps/` | consulta historica |
| `docs/archive/security-roadmaps/git-commit-guide.md` | `docs/archive/security-roadmaps/` | consulta historica |
| `.github/ISSUE_TEMPLATE/security-incident.md` | `.github/ISSUE_TEMPLATE/` | qualquer pessoa que encontre uma falha |

## Como usar cada documento

### `SECURITY.md`

Politica publica de reporte e tratamento de vulnerabilidades. E o ponto de entrada para a comunidade.

### `vps-security-plan.md`

Documento principal do baseline de seguranca em 9 camadas. Use como referencia tecnica de infraestrutura, banco, API, LLM/RAG, CI/CD e LGPD.

### `llm-confinement.md`

Registra a decisao arquitetural de confinamento por design. Use antes de mexer em prompt, handoff, dominio ou higiene de entrada relacionada a seguranca.

### `implementation-tracking.md`

Snapshot historico dos milestones, issues e responsaveis originais. Para
execucao atual, use o plano tecnico e a Fase 0.

### `git-commit-guide.md`

Registro historico da trilha inicial. Para contribuicao atual, use
`.agents/skills/supportfaq-git-flow/SKILL.md`.

### `security-incident.md`

Template publico de incidente para evitar relato incompleto ou exposicao indevida em issue.

## Observacao de organizacao

Este arquivo substitui a necessidade do antigo `ESTRUTURA-E-COMMITS.md`, que ficou redundante depois que o pacote de seguranca ja foi publicado na `main`.

## Checklist rapido de banco

Contexto: o banco `supportfaqagent` ja existe e a trilha de seguranca precisa garantir acesso controlado e caminho de producao minimo.

### Passo 0

Trocar qualquer senha que tenha circulado fora de canal privado.

### Passo 1

Confirmar acesso de desenvolvimento apenas via tunel SSH.

### Passo 2

Criar usuario de producao com privilegio minimo e registrar isso em migration ou documento apropriado.

### Passo 3

Configurar `.env` local de cada dev sem versionar segredo.

### Passo 4

Rodar os testes SQL e validar extensoes, schema, idempotencia, busca vetorial e isolamento por dominio.

### Passo 5

Documentar quem acessa o banco, como acessa e qual o processo para novo dev.

### Passo 6

Quando a VPS definitiva estiver pronta, migrar o banco, rerodar testes e atualizar variaveis de ambiente.
