# 🔀 Guia de Git — Implementação de Segurança
**supportFAQagent | Para o time: Renan, Alexandre, Juliano, Silotto**

---

## Convenção de branches para segurança

Todo trabalho de segurança segue o prefixo `security/` + o código da Issue:

```
security/SEC-001-rotacionar-ip-vps
security/SEC-002-fechar-porta-5432
security/SEC-003-trocar-credenciais-banco
security/SEC-004-configurar-ufw
security/SEC-005-docker-rede-interna
security/SEC-006-cloudflare-https
security/SEC-007-usuario-prod-db
security/SEC-008-backup-automatico
security/SEC-009-auditoria-git
security/SEC-010-api-key-endpoints
security/SEC-011-prompt-injection
security/SEC-012-rate-limiting
security/SEC-013-system-prompt
security/SEC-014-branch-protection
security/SEC-015-cicd-gitleaks
security/SEC-016-anonimizacao-lgpd
security/SEC-017-runbook-incidentes
security/SEC-018-publicacao-final
```

---

## Fluxo de trabalho por Issue

```bash
# 1. Sempre sincronizar com a main antes de começar
git checkout main
git pull origin main

# 2. Criar branch da Issue
git checkout -b security/SEC-XXX-descricao-curta

# 3. Trabalhar em commits pequenos e focados
git add arquivo-especifico.py
git commit -m "security(SEC-XXX): descrição objetiva do que foi feito"

# 4. Revisar antes de subir
git status
git diff HEAD~1

# 5. Push e abrir PR
git push -u origin security/SEC-XXX-descricao-curta
```

---

## Convenção de mensagens de commit

```
security(SEC-XXX): <o que foi feito>

[corpo opcional — contexto adicional]

Closes #SEC-XXX
```

### Exemplos reais deste projeto

```bash
# Issues de incidente imediato (M0)
git commit -m "security(SEC-002): fechar porta 5432 no docker-compose"
git commit -m "security(SEC-003): trocar senha renan_faq e atualizar env.example"
git commit -m "security(SEC-009): adicionar .env e *.key ao .gitignore"

# Issues de infraestrutura (M1)
git commit -m "security(SEC-004): aplicar regras UFW para IPs do time"
git commit -m "security(SEC-005): isolar postgres na rede interna Docker"
git commit -m "security(SEC-006): adicionar docs de configuração Cloudflare"

# Issues de API e LLM (M3)
git commit -m "security(SEC-010): implementar verify_api_key nos endpoints"
git commit -m "security(SEC-011): implementar contrato de identidade no domain.yaml"
git commit -m "security(SEC-012): implementar rate limiting 30req/min no /chat"
git commit -m "security(SEC-013): implementar confinamento por design no system prompt"

# Issues de CI/CD (M4)
git commit -m "security(SEC-015): adicionar workflow CI com gitleaks e safety"

# Documentação (M5)
git commit -m "security(SEC-017): criar runbook de resposta a incidentes"
git commit -m "security(SEC-018): publicar SECURITY.md e plano de segurança"
```

---

## Checklist obrigatório antes de abrir PR de segurança

```markdown
## Checklist de Segurança — PR

### O código não introduz novos riscos
- [ ] Nenhuma credencial, IP, senha ou token foi adicionado ao código
- [ ] Nenhum arquivo `.env` real foi incluído no commit
- [ ] `gitleaks detect --source .` retorna 0 findings

### A mudança resolve o que se propõe
- [ ] A Issue correspondente (SEC-XXX) está referenciada no PR
- [ ] O `Definition of Done` da Issue foi atendido
- [ ] Foi testado localmente antes do PR

### Não quebra o projeto
- [ ] `pytest tests/` passa sem erros
- [ ] Se a mudança afeta o banco: migration documentada em `migrations/`
- [ ] Se a mudança afeta a API: `.env.example` atualizado

### Revisão
- [ ] Pelo menos 1 membro do time revisou antes do merge
- [ ] Mudanças críticas (banco, firewall, autenticação) foram discutidas no grupo antes
```

---

## Template de PR — Segurança

Criar em `.github/pull_request_template.md`:

```markdown
## 🛡️ PR de Segurança — [SEC-XXX] Título da Issue

### O que este PR faz
<!-- Descreva em 2-3 linhas o que foi implementado -->

### Issue relacionada
Closes #SEC-XXX

### Milestone
- [ ] M0 — Incidentes Imediatos
- [ ] M1 — Infraestrutura VPS
- [ ] M2 — Banco e Segredos
- [ ] M3 — API e LLM
- [ ] M4 — Git e CI/CD
- [ ] M5 — Docs e LGPD

### Como testar
<!-- Passo a passo para o revisor verificar que funciona -->
1.
2.
3.

### Checklist
- [ ] Sem segredos no código (`gitleaks` passou)
- [ ] `pytest tests/` passa
- [ ] `pytest tests/security/` passa
- [ ] `.env.example` atualizado (se necessário)
- [ ] Documentação atualizada (se necessário)
- [ ] Definition of Done da Issue atendido

### Notas para o revisor
<!-- Algo que o revisor deve prestar atenção especial -->
```

---

## Labels necessárias no repositório

Criar em `https://github.com/renanfulas/supportFAQagent/labels`:

| Label | Cor | Uso |
|---|---|---|
| `security` | `#e11d48` (vermelho) | Todas as Issues e PRs de segurança |
| `priority/critical` | `#7f1d1d` (vermelho escuro) | Incidentes imediatos (M0) |
| `priority/high` | `#dc2626` | Sprint 1 e 2 |
| `priority/medium` | `#f97316` | Sprint 3 |
| `infrastructure` | `#0ea5e9` | Firewall, Docker, Cloudflare |
| `database` | `#8b5cf6` | PostgreSQL, migrations, backup |
| `api` | `#10b981` | FastAPI, endpoints, rate limit |
| `llm` | `#f59e0b` | Prompt, RAG, LangChain |
| `cicd` | `#6366f1` | GitHub Actions, gitleaks |
| `lgpd` | `#78716c` | Privacidade, anonimização |
| `documentation` | `#64748b` | Docs, runbooks |

---

## Sequência de commits recomendada por membro

### Renan Junior (arquitetura, API, CI/CD)
```bash
# Semana 1
security/SEC-009-auditoria-git
security/SEC-004-configurar-ufw          # em conjunto com Silotto

# Semana 2
security/SEC-010-api-key-endpoints
security/SEC-011-confinamento-domain-yaml    # em conjunto com Juliano
security/SEC-012-rate-limiting
security/SEC-013-confinamento-system-prompt  # em conjunto com Juliano
security/SEC-014-branch-protection
security/SEC-015-cicd-gitleaks

# Semana 3
security/SEC-017-runbook-incidentes
security/SEC-018-publicacao-final
```

### Alexandre Madeira (banco, n8n, infra)
```bash
# Hoje (bloqueante)
security/SEC-002-fechar-porta-5432
security/SEC-003-trocar-credenciais-banco

# Semana 1
security/SEC-005-docker-rede-interna
security/SEC-007-usuario-prod-db
security/SEC-008-backup-automatico
```

### Juliano Barreto (LangChain, RAG, embeddings)
```bash
# Semana 2 (em conjunto com Renan)
security/SEC-011-confinamento-domain-yaml
security/SEC-013-confinamento-system-prompt
# Semana 3
security/SEC-016-anonimizacao-lgpd
```

### Silotto / HostGator (VPS, infra, domínio)
```bash
# Hoje (bloqueante)
security/SEC-001-rotacionar-ip-vps

# Semana 1
security/SEC-004-configurar-ufw          # em conjunto com Renan
security/SEC-006-cloudflare-https        # em conjunto com Renan

# Semana 3
security/SEC-018-publicacao-final        # em conjunto com Renan
```

---

## Tag de release ao final

Quando o M5 estiver concluído:

```bash
git checkout main
git pull origin main
git tag -a v0.1.0-security-baseline -m "Baseline de segurança implementado — Plano SEC v1.0"
git push origin v0.1.0-security-baseline
```

Criar release no GitHub com:
- **Tag:** `v0.1.0-security-baseline`
- **Título:** `v0.1.0 — Security Baseline`
- **Notas:** link para `docs/security/implementation-tracking.md`

---

*Guia mantido por: Renan Junior | Revisado pelo time no Meetup HostGator — Quinta, 17h*
