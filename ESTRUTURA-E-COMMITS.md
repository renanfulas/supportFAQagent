# 📁 Estrutura de Documentação de Segurança
## supportFAQagent — O que commitar e onde

---

## Visão geral da estrutura no repositório

```
supportFAQagent/
│
├── SECURITY.md                          ← Política pública (raiz do repo, padrão GitHub)
│
├── .github/
│   ├── pull_request_template.md         ← Template de PR com checklist de segurança
│   ├── ISSUE_TEMPLATE/
│   │   └── security-incident.md         ← Template para reportar incidentes
│   └── workflows/
│       └── ci.yml                       ← GitHub Actions: gitleaks + safety + pytest
│
├── docs/
│   └── security/
│       ├── vps-security-plan.md         ← Plano completo (9 camadas) — documento principal
│       ├── llm-confinement.md           ← Decisão arquitetural: confinamento por design ← NOVO
│       ├── implementation-tracking.md   ← Issues, milestones, quadro de acompanhamento
│       └── git-commit-guide.md          ← Convenções de branch e commit para segurança
│
├── migrations/
│   ├── 001_initial_schema.sql           ← Já existe (Alexandre) ✅
│   └── 002_production_users.sql         ← A criar (SEC-007)
│
├── scripts/
│   ├── backup_postgres.sh               ← A criar (SEC-008)
│   └── anonymize_tickets.py             ← A criar (SEC-016)
│
└── tests/
    └── security/
        ├── test_confinement.py          ← A criar (SEC-011)
        └── test_auth.py                 ← A criar (SEC-010)
```

---

## O que já existe vs. o que criar

| Arquivo | Status | Issue | Responsável |
|---|---|---|---|
| `SECURITY.md` | 🆕 Criar | SEC-018 | Renan |
| `.github/pull_request_template.md` | 🆕 Criar | SEC-014 | Renan |
| `.github/workflows/ci.yml` | 🆕 Criar | SEC-015 | Renan |
| `docs/security/vps-security-plan.md` | 🆕 Criar | SEC-018 | Renan |
| `docs/security/llm-confinement.md` | 🆕 Criar | SEC-011 | Renan |
| `docs/security/implementation-tracking.md` | 🆕 Criar | SEC-018 | Renan |
| `docs/security/git-commit-guide.md` | 🆕 Criar | SEC-018 | Renan |
| `migrations/001_initial_schema.sql` | ✅ Existe | — | Alexandre |
| `migrations/002_production_users.sql` | 🆕 Criar | SEC-007 | Alexandre |
| `scripts/backup_postgres.sh` | 🆕 Criar | SEC-008 | Alexandre |
| `scripts/anonymize_tickets.py` | 🆕 Criar | SEC-016 | Juliano |
| `tests/security/test_confinement.py` | 🆕 Criar | SEC-011 | Renan + Juliano |
| `tests/security/test_auth.py` | 🆕 Criar | SEC-010 | Renan |
| `app/core/security.py` | 🆕 Criar | SEC-010 | Renan |
| `app/core/sanitize.py` | 🆕 Criar | SEC-011 | Renan | higiene de input, não defesa de injeção |
| `app/core/rate_limit.py` | 🆕 Criar | SEC-012 | Renan |

---

## Ordem de commit recomendada

### 🔴 HOJE — Antes de qualquer outra coisa

```bash
# 1. Alexandre — fecha porta do banco
git checkout -b security/SEC-002-fechar-porta-5432
# (editar docker-compose.yml, remover ports: do postgres)
git commit -m "security(SEC-002): remover exposição externa da porta 5432"
git push && abrir PR

# 2. Alexandre — troca credenciais
git checkout -b security/SEC-003-trocar-credenciais-banco
# (atualizar .env.example sem revelar a senha real)
git commit -m "security(SEC-003): atualizar .env.example com novas variáveis de banco"
git push && abrir PR

# 3. Renan — auditoria de segredos
git checkout -b security/SEC-009-auditoria-git
# (adicionar entradas ao .gitignore, rodar gitleaks, adicionar .gitleaks.toml)
git commit -m "security(SEC-009): fortalecer .gitignore e adicionar .gitleaks.toml"
git push && abrir PR
```

### ⚪ SEMANA 1 — Infraestrutura e banco

```bash
# SEC-005: Docker rede interna (Alexandre)
# SEC-007: Usuário de produção no banco (Alexandre)
# SEC-008: Script de backup (Alexandre)
# SEC-004: UFW na VPS (Silotto + Renan — via documentação)
# SEC-006: Cloudflare (Silotto + Renan — via documentação)
```

### ⚪ SEMANA 2 — API, LLM, CI/CD

```bash
# SEC-010: API Key (Renan)
# SEC-011: Confinamento por design (Renan + Juliano)
# SEC-012: Rate limiting (Renan)
# SEC-013: Confinamento system prompt (Renan + Juliano)
# SEC-014: Branch protection (Renan — via GitHub UI, sem commit)
# SEC-015: GitHub Actions CI (Renan)
```

### ⚪ SEMANA 3 — Docs, LGPD, publicação

```bash
# SEC-016: Anonimização (Juliano)
# SEC-017: Runbook de incidentes (Renan)
# SEC-018: Publicação final + tag v0.1.0-security-baseline (Renan + Silotto)
```

---

## Arquivos deste pacote — prontos para commitar

Todos os arquivos abaixo foram gerados e estão prontos para entrar no repositório:

| Arquivo | Commitar em |
|---|---|
| `SECURITY.md` | Raiz do repositório |
| `docs/security/vps-security-plan.md` | `docs/security/` |
| `docs/security/implementation-tracking.md` | `docs/security/` |
| `docs/security/git-commit-guide.md` | `docs/security/` |

**Commit sugerido para subir tudo de uma vez:**

```bash
git checkout -b security/SEC-018-baseline-docs
git add SECURITY.md docs/security/
git commit -m "security(SEC-018): adicionar política, plano e guia de segurança

- SECURITY.md: política pública de segurança do repositório
- docs/security/vps-security-plan.md: plano de 9 camadas para a VPS
- docs/security/llm-confinement.md: decisão arquitetural — confinamento por design
- docs/security/implementation-tracking.md: 18 issues com responsáveis e milestones
- docs/security/git-commit-guide.md: convenção de branch/commit para segurança

Ref: Plano gerado a partir das conversas do grupo Support LLM - OPEN Source
Meetup de apresentação: HostGator — Quinta, 17h"
git push -u origin security/SEC-018-baseline-docs
```

---

*Gerado para a comunidade supportFAQagent | HostGator Open Source Initiative*
*Time: Renan Junior · Alexandre Madeira · Juliano Barreto · Silotto*
