# 📋 Acompanhamento — Implementação do Plano de Segurança
**supportFAQagent | Open Source**
**Atualizado em: Maio/2026**

---

## Estrutura de Milestones no GitHub

Este documento mapeia cada ação do plano de segurança para uma **Issue**, um **responsável** e uma **milestone** no GitHub.

Criar as seguintes milestones em: `https://github.com/renanfulas/supportFAQagent/milestones`

| # | Milestone | Prazo | Objetivo |
|---|---|---|---|
| M0 | `security/incidentes-imediatos` | **Hoje** | Fechar brechas abertas nas conversas do grupo |
| M1 | `security/infraestrutura-vps` | Sprint 1 (semana 1) | Firewall, Docker, Cloudflare, HTTPS |
| M2 | `security/banco-e-segredos` | Sprint 1 (semana 1) | Credenciais, backup, usuários do banco |
| M3 | `security/api-e-llm` | Sprint 2 (semana 2) | Autenticação, rate limit, confinamento por design |
| M4 | `security/git-e-cicd` | Sprint 2 (semana 2) | Branch protection, GitHub Actions, gitleaks |
| M5 | `security/docs-e-lgpd` | Sprint 3 (semana 3) | Documentação final, anonimização, LGPD |

---

## M0 — Incidentes Imediatos (Hoje)

> **Bloqueante.** Nada avança para produção sem estes itens fechados.

---

### Issue #SEC-001 — Rotacionar IP da VPS

```
Título: [SEC] Rotacionar ou mascarar IP da VPS exposto no grupo
Labels: security, priority/critical, milestone/M0
Assignee: Silotto
```

**Contexto:**
O IP `177.145.71.104` foi compartilhado no grupo do WhatsApp em 11/05/2026.
Qualquer pessoa que tiver acesso ao histórico do grupo conhece este IP.

**Tarefas:**
- [ ] Solicitar rotação do IP à HostGator OU
- [ ] Ativar proxy Cloudflare antes de qualquer divulgação pública
- [ ] Confirmar que o IP antigo não responde mais às portas do projeto

**Definition of Done:** IP real da VPS não é acessível diretamente pela internet.

---

### Issue #SEC-002 — Fechar porta 5432 externamente

```
Título: [SEC] Revogar acesso externo à porta 5432 (PostgreSQL)
Labels: security, priority/critical, milestone/M0
Assignee: Alexandre Madeira
```

**Contexto:**
Em 11/05/2026, foi liberada a porta 5432 para o IP `177.145.71.104` (Renan) no firewall da VPS.
PostgreSQL nunca deve ser acessível pela internet.

**Tarefas:**
- [ ] Revogar a regra de firewall para o IP do Renan na porta 5432
- [ ] Verificar `sudo ufw status` e confirmar que 5432 não está aberta
- [ ] Configurar acesso ao banco via túnel SSH (ver docs/security/vps-security-plan.md)
- [ ] Testar que a conexão ao banco funciona via túnel

**Comando de verificação:**
```bash
sudo ufw status | grep 5432
# Esperado: sem resultado (regra não existe)
```

**Definition of Done:** `nmap -p 5432 IP_DA_VPS` retorna `filtered` ou `closed`.

---

### Issue #SEC-003 — Trocar credenciais do banco expostas

```
Título: [SEC] Trocar senha do usuário renan_faq e auditoria de credenciais
Labels: security, priority/critical, milestone/M0
Assignee: Alexandre Madeira + Renan Junior
```

**Contexto:**
Credenciais de banco foram discutidas e compartilhadas em mídias no grupo WhatsApp.
Usuário `renan_faq` foi criado com senha que circulou no grupo.

**Tarefas:**
- [ ] Trocar senha do usuário `renan_faq` no banco
- [ ] Gerar nova senha com `openssl rand -base64 32`
- [ ] Atualizar `.env` local de cada dev com a nova senha (via DM, não pelo grupo)
- [ ] Deletar mensagens com mídias sensíveis do grupo WhatsApp
- [ ] Auditar o histórico Git por credenciais com `gitleaks detect --source .`

**Definition of Done:** Nenhuma credencial ativa circula em canal aberto.

---

## M1 — Infraestrutura VPS (Sprint 1)

---

### Issue #SEC-004 — Configurar firewall UFW na VPS da HostGator

```
Título: [SEC] Configurar UFW com regras mínimas na VPS de produção
Labels: security, infrastructure, milestone/M1
Assignee: Silotto + Renan Junior
```

**Tarefas:**
- [ ] Coletar IPs fixos (ou ranges) de Renan, Alexandre, Silotto, Juliano
- [ ] Aplicar configuração UFW conforme `docs/security/vps-security-plan.md`
- [ ] SSH liberado apenas para IPs do time
- [ ] HTTP (80) e HTTPS (443) abertos para o mundo
- [ ] Todas as demais portas fechadas por padrão
- [ ] Testar acesso SSH após configuração antes de fechar sessão atual

**Definition of Done:** `sudo ufw status verbose` mostra apenas regras documentadas.

---

### Issue #SEC-005 — Isolar PostgreSQL na rede interna do Docker

```
Título: [SEC] Configurar rede Docker interna — banco sem exposição de porta
Labels: security, infrastructure, docker, milestone/M1
Assignee: Alexandre Madeira + Renan Junior
```

**Tarefas:**
- [ ] Revisar `docker-compose.yml` e remover `ports:` do serviço `postgres`
- [ ] Criar rede `internal` isolada para banco, API e n8n
- [ ] Confirmar que API conecta no banco via hostname do container (não via `localhost`)
- [ ] Testar que `psql -h IP_EXTERNO -p 5432` falha após a mudança
- [ ] Documentar o novo `docker-compose.yml` em `docs/infrastructure/`

**Definition of Done:** Banco acessível apenas dentro da rede Docker interna.

---

### Issue #SEC-006 — Configurar Cloudflare e HTTPS no domínio

```
Título: [SEC] Ativar Cloudflare com proxy e HTTPS para o domínio do projeto
Labels: security, infrastructure, milestone/M1
Assignee: Silotto + Renan Junior
```

**Tarefas:**
- [ ] Registrar domínio na HostGator (definir nome com o time)
- [ ] Apontar nameservers para o Cloudflare
- [ ] Criar registro `A` com proxy ativo (ícone laranja)
- [ ] Ativar SSL/TLS modo **Full (strict)**
- [ ] Criar regra de redirecionamento HTTP → HTTPS
- [ ] Configurar rate limit: 30 req/min por IP no endpoint `/chat`
- [ ] Testar com `curl -I https://dominio` e verificar headers

**Definition of Done:** `https://dominio/chat` responde com certificado válido, HTTP redireciona para HTTPS.

---

## M2 — Banco e Segredos (Sprint 1)

---

### Issue #SEC-007 — Criar usuário de produção com privilégios mínimos

```
Título: [SEC] Usuário PostgreSQL de produção com acesso restrito
Labels: security, database, milestone/M2
Assignee: Alexandre Madeira
```

**Tarefas:**
- [ ] Criar usuário `supportfaq_prod` com `openssl rand -base64 32`
- [ ] Conceder apenas SELECT/INSERT/UPDATE nas tabelas necessárias
- [ ] Criar usuário `supportfaq_readonly` para evals/métricas
- [ ] Revogar DELETE em tabelas críticas (ex: `domains`)
- [ ] Documentar o script SQL em `migrations/002_production_users.sql`
- [ ] Atualizar `.env.example` com as novas variáveis de usuário

**Definition of Done:** App de produção conecta com `supportfaq_prod`, não com o usuário admin.

---

### Issue #SEC-008 — Script de backup automático do banco

```
Título: [SEC] Configurar backup diário automatizado do PostgreSQL
Labels: security, database, milestone/M2
Assignee: Alexandre Madeira
```

**Tarefas:**
- [ ] Criar `scripts/backup_postgres.sh` (ver modelo em `docs/security/vps-security-plan.md`)
- [ ] Configurar cron para rodar às 02h diariamente
- [ ] Testar backup e restore de um dump gerado
- [ ] Definir retenção: 7 dias locais na VPS
- [ ] Documentar processo de restore em `docs/runbooks/restore-backup.md`

**Definition of Done:** Backup roda automaticamente, restore foi testado com sucesso.

---

### Issue #SEC-009 — Auditoria de segredos e `.gitignore`

```
Título: [SEC] Auditar histórico Git por segredos e validar .gitignore
Labels: security, git, milestone/M2
Assignee: Renan Junior
```

**Tarefas:**
- [ ] Instalar e rodar `gitleaks detect --source . --report-format json`
- [ ] Analisar relatório e revogar qualquer chave encontrada
- [ ] Verificar que `.env`, `.env.*` (exceto `.env.example`) estão no `.gitignore`
- [ ] Verificar que `*.pem`, `*.key`, `id_rsa` estão no `.gitignore`
- [ ] Adicionar `.gitleaks.toml` ao projeto para configuração da auditoria
- [ ] Commitar resultado limpo em `security/audit-githistory`

**Definition of Done:** `gitleaks detect` retorna 0 findings no repositório.

---

## M3 — API e LLM (Sprint 2)

---

### Issue #SEC-010 — Autenticação por API Key nos endpoints

```
Título: [SEC] Implementar autenticação X-API-Key em todos os endpoints
Labels: security, api, milestone/M3
Assignee: Renan Junior
```

**Tarefas:**
- [ ] Criar `app/core/security.py` com `verify_api_key`
- [ ] Aplicar `Depends(verify_api_key)` em `/chat`, `/feedback`, `/ingestion/preview`
- [ ] Adicionar `API_SECRET_KEY` ao `.env.example`
- [ ] Escrever testes em `tests/api/test_auth.py`
- [ ] Documentar uso da API Key em `docs/api-usage.md`

**Definition of Done:** Todos os endpoints retornam 403 sem API Key válida.

---

### Issue #SEC-011 — Confinamento por design: contrato de identidade do agente

```
Título: [SEC] Implementar confinamento por design — contrato de identidade no domain.yaml
Labels: security, llm, milestone/M3
Assignee: Renan Junior + Juliano Barreto
```

**Contexto:**
A defesa contra prompt injection neste projeto não é baseada em detectar padrões de ataque na entrada do usuário — essa abordagem é um labirinto reativo sem fim. A defesa real é o confinamento por design: o agente é construído para não saber fazer outra coisa além do seu domínio. Decisão arquitetural documentada em `docs/security/llm-confinement.md`.

**Tarefas:**
- [ ] Definir `identity`, `scope`, `behavior` e `escalation` no `domains/suporte-vps-whatsapp/domain.yaml`
- [ ] Implementar system prompt com contrato fechado em `domains/suporte-vps-whatsapp/prompts/system.txt`
- [ ] Garantir que `prompt_builder.py` usa o contrato do `domain.yaml` sem adicionar lógica própria
- [ ] Criar `app/core/sanitize.py` como higiene de input apenas (tamanho, formato) — documentar que **não é defesa de injeção**
- [ ] Criar evals de confinamento em `domains/suporte-vps-whatsapp/evals/confinement/`
- [ ] Escrever testes em `tests/security/test_confinement.py`

**Definition of Done:** Agente responde fora do escopo com escalation — nunca com alucinação ou obediência a instrução injetada.

---

### Issue #SEC-012 — Rate limiting na API

```
Título: [SEC] Implementar rate limiting no endpoint /chat
Labels: security, api, milestone/M3
Assignee: Renan Junior
```

**Tarefas:**
- [ ] Implementar middleware de rate limiting em `app/core/rate_limit.py`
- [ ] Configurar: 30 req/min por IP no `/chat`
- [ ] Retornar erro 429 com header `Retry-After`
- [ ] Testar com script de carga simples
- [ ] Adicionar configuração via variável de ambiente `RATE_LIMIT_PER_MINUTE`

**Definition of Done:** Após 30 req/min, API retorna 429 para o IP.

---

### Issue #SEC-013 — Implementar confinamento por design no system prompt

```
Título: [SEC] Implementar confinamento por design — system prompt com contrato fechado
Labels: security, llm, milestone/M3
Assignee: Renan Junior + Juliano Barreto
```

**Contexto:**
Um system prompt endurecido não é uma lista de regras "não faça isso". É um contrato de identidade tão específico que o agente não tem como sair do escopo — não por proibição, mas por construção. Ver `docs/security/llm-confinement.md`.

**Tarefas:**
- [ ] Revisar `domains/suporte-vps-whatsapp/prompts/system.txt` com contrato de identidade restrita
- [ ] Definir comportamento explícito para perguntas fora do escopo (escalar, nunca improvisar)
- [ ] Definir comportamento para tentativas de redefinição (ignorar silenciosamente, escalar)
- [ ] Validar que o agente não revela o system prompt quando perguntado diretamente
- [ ] Criar evals específicos para cada comportamento definido
- [ ] Documentar decisões de confinamento no `domain.yaml` sob a chave `behavior`

**Definition of Done:** Evals de confinamento passam — agente escala 100% das tentativas de redefinição de identidade ou escopo.

---

## M4 — Git e CI/CD (Sprint 2)

---

### Issue #SEC-014 — Branch protection na main

```
Título: [SEC] Ativar branch protection rules na branch main
Labels: security, git, milestone/M4
Assignee: Renan Junior
```

**Tarefas:**
- [ ] Ativar em: Settings → Branches → Branch protection rules
- [ ] Exigir PR com pelo menos 1 aprovação
- [ ] Exigir que status checks passem antes do merge
- [ ] Bloquear push direto na main
- [ ] Documentar o fluxo em `CONTRIBUTING.md`

**Definition of Done:** Push direto na main é bloqueado para todos, incluindo admins.

---

### Issue #SEC-015 — GitHub Actions com gitleaks e testes de segurança

```
Título: [SEC] Configurar CI com detecção de segredos e testes automáticos
Labels: security, cicd, milestone/M4
Assignee: Renan Junior
```

**Tarefas:**
- [ ] Criar `.github/workflows/ci.yml`
- [ ] Etapa: gitleaks para detectar segredos commitados
- [ ] Etapa: `safety check` para vulnerabilidades em dependências
- [ ] Etapa: `pytest tests/` com cobertura mínima de 70%
- [ ] Etapa: `pytest tests/security/` separado e obrigatório
- [ ] Bloquear merge se qualquer etapa falhar

**Definition of Done:** Todo PR dispara o CI e falha se houver segredos ou testes quebrando.

---

## M5 — Docs e LGPD (Sprint 3)

---

### Issue #SEC-016 — Documentar processo de anonimização de dados

```
Título: [SEC] Pipeline de anonimização de chamados históricos (LGPD)
Labels: security, lgpd, data, milestone/M5
Assignee: Juliano Barreto
```

**Contexto:**
Foi discutido no grupo o uso de chamados históricos reais da HostGator para treinar o RAG.

**Tarefas:**
- [ ] Criar `scripts/anonymize_tickets.py` que remove: nome, e-mail, CPF, telefone, IP
- [ ] Testar com o arquivo `data/dummy_tickets.csv`
- [ ] Documentar o processo em `docs/data/anonymization.md`
- [ ] Definir retenção de conversas: 90 dias
- [ ] Adicionar aviso de privacidade ao `README.md`

**Definition of Done:** Nenhum dado pessoal identificável entra no pipeline RAG.

---

### Issue #SEC-017 — Runbook de resposta a incidentes

```
Título: [SEC] Criar runbook de resposta a incidentes de segurança
Labels: security, documentation, milestone/M5
Assignee: Renan Junior
```

**Tarefas:**
- [ ] Criar `docs/runbooks/security-incident-response.md`
- [ ] Cobrir: credencial exposta, banco comprometido, IP vazado, prompt injection em produção
- [ ] Definir canal de comunicação de incidentes (DM vs grupo privado)
- [ ] Definir SLA de resposta por severidade
- [ ] Revisar com o time antes de publicar

**Definition of Done:** Runbook revisado e mergeado na `main`.

---

### Issue #SEC-018 — Revisão final e publicação do plano

```
Título: [SEC] Revisão final do plano de segurança e publicação para a comunidade
Labels: security, documentation, milestone/M5
Assignee: Renan Junior + Silotto
```

**Tarefas:**
- [ ] Mover `docs/security/vps-security-plan.md` para o repositório
- [ ] Publicar `SECURITY.md` na raiz do repositório
- [ ] Atualizar o `README.md` com link para a política de segurança
- [ ] Apresentar o plano no Meetup da HostGator (quinta, 17h)
- [ ] Criar release tag `v0.1.0-security-baseline`

**Definition of Done:** Plano publicado, apresentado no Meetup, tag criada.

---

## Quadro de Acompanhamento Semanal

| Issue | Título resumido | Responsável | Status | Semana |
|---|---|---|---|---|
| SEC-001 | Rotacionar IP VPS | Silotto | 🔴 Aberta | Hoje |
| SEC-002 | Fechar porta 5432 | Alexandre | 🔴 Aberta | Hoje |
| SEC-003 | Trocar credenciais banco | Alexandre + Renan | 🔴 Aberta | Hoje |
| SEC-004 | Configurar UFW | Silotto + Renan | ⚪ Planejada | Semana 1 |
| SEC-005 | Docker rede interna | Alexandre + Renan | ⚪ Planejada | Semana 1 |
| SEC-006 | Cloudflare + HTTPS | Silotto + Renan | ⚪ Planejada | Semana 1 |
| SEC-007 | Usuário prod DB | Alexandre | ⚪ Planejada | Semana 1 |
| SEC-008 | Backup automático | Alexandre | ⚪ Planejada | Semana 1 |
| SEC-009 | Auditoria Git | Renan | ⚪ Planejada | Semana 1 |
| SEC-010 | API Key endpoints | Renan | ⚪ Planejada | Semana 2 |
| SEC-011 | Confinamento por design — domain.yaml | Renan + Juliano | ⚪ Planejada | Semana 2 |
| SEC-012 | Rate limiting | Renan | ⚪ Planejada | Semana 2 |
| SEC-013 | Confinamento — system prompt | Renan + Juliano | ⚪ Planejada | Semana 2 |
| SEC-014 | Branch protection | Renan | ⚪ Planejada | Semana 2 |
| SEC-015 | CI/CD + gitleaks | Renan | ⚪ Planejada | Semana 2 |
| SEC-016 | Anonimização LGPD | Juliano | ⚪ Planejada | Semana 3 |
| SEC-017 | Runbook incidentes | Renan | ⚪ Planejada | Semana 3 |
| SEC-018 | Publicação final | Renan + Silotto | ⚪ Planejada | Semana 3 |

**Legenda:** 🔴 Bloqueante | 🟡 Em andamento | 🟢 Concluída | ⚪ Planejada

---

*Atualizar este quadro a cada PR mergeado no repositório.*
*Próxima revisão presencial: Meetup HostGator — Quinta, 17h.*
