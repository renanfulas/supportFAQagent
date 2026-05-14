# Acompanhamento - Implementacao do Plano de Seguranca
**supportFAQagent | Open Source**
**Atualizado em: Maio/2026**

Este documento publico registra o roadmap de seguranca do projeto sem expor IPs reais, nomes de usuarios internos, credenciais, hostnames ou detalhes operacionais do ambiente.

## Estrutura de milestones

| # | Milestone | Prazo | Objetivo |
|---|---|---|---|
| M0 | `security/incidentes-imediatos` | Hoje | Fechar brechas iniciais antes de producao |
| M1 | `security/infraestrutura-vps` | Sprint 1 | Firewall, Docker, Cloudflare, HTTPS |
| M2 | `security/banco-e-segredos` | Sprint 1 | Credenciais, backup, usuarios do banco |
| M3 | `security/api-e-llm` | Sprint 2 | Autenticacao, rate limit, confinamento |
| M4 | `security/git-e-cicd` | Sprint 2 | Branch protection, CI, gitleaks |
| M5 | `security/docs-e-lgpd` | Sprint 3 | Publicacao, anonimização, runbooks |

## M0 - Incidentes imediatos

### SEC-001 - Rotacionar ou mascarar IP da VPS

**Contexto:**
Um IP de infraestrutura foi compartilhado em canal de comunicacao do time. Em documento publico, os detalhes reais ficam fora do repositório.

**Tarefas:**
- [ ] Rotacionar o IP ou mascarar por proxy de borda
- [ ] Confirmar que o IP real nao fica exposto publicamente
- [ ] Mover detalhes do incidente para documento privado

**Definition of Done:** a infraestrutura nao expõe IP real diretamente para o publico.

### SEC-002 - Fechar acesso externo ao PostgreSQL

**Contexto:**
Uma excecao temporaria permitiu acesso externo ao banco durante a fase inicial. PostgreSQL nao deve ficar acessivel pela internet.

**Tarefas:**
- [ ] Revogar regras temporarias de firewall para a porta do banco
- [ ] Confirmar que o banco so e acessivel por tunel SSH ou rede interna
- [ ] Validar com teste externo que a porta nao responde publicamente

**Definition of Done:** a porta do banco responde como `filtered` ou `closed` externamente.

### SEC-003 - Trocar credenciais expostas

**Contexto:**
Credenciais circularam em canal de comunicacao do time na fase inicial. Nomes reais de usuario e valores de segredo nao devem aparecer em documento publico.

**Tarefas:**
- [ ] Trocar credenciais afetadas
- [ ] Distribuir novos segredos apenas por canal privado
- [ ] Auditar historico Git e materiais compartilhados

**Definition of Done:** nenhuma credencial ativa continua exposta.

## M1 - Infraestrutura VPS

### SEC-004 - Configurar firewall minimo
- [ ] Restringir SSH por IP do time
- [ ] Liberar apenas HTTP e HTTPS para o mundo
- [ ] Manter demais portas fechadas por padrao

### SEC-005 - Isolar PostgreSQL em rede interna
- [ ] Remover exposicao direta do banco no host
- [ ] Usar rede Docker interna para banco, API e automacoes
- [ ] Validar que o banco nao fica acessivel externamente

### SEC-006 - Cloudflare e HTTPS
- [ ] Proteger o dominio por proxy de borda
- [ ] Forcar HTTPS
- [ ] Aplicar rate limit de borda no endpoint de chat

## M2 - Banco e segredos

### SEC-007 - Usuario de producao com privilegios minimos
- [ ] Criar usuario de aplicacao com privilegios restritos
- [ ] Criar usuario somente leitura para analise e evals
- [ ] Documentar estrategia SQL sem expor credenciais reais

### SEC-008 - Backup automatico
- [ ] Criar script de backup
- [ ] Testar restore
- [ ] Definir retencao

### SEC-009 - Auditoria de segredos
- [ ] Rodar gitleaks
- [ ] Validar `.gitignore`
- [ ] Manter `.gitleaks.toml` no projeto

## M3 - API e LLM

### SEC-010 - Autenticacao por API key
- [ ] Proteger endpoints sensiveis
- [ ] Documentar `X-API-Key`
- [ ] Testar `403` sem chave valida

### SEC-011 - Contrato de identidade do agente
- [ ] Formalizar comportamento de dominio
- [ ] Validar suites de confinamento
- [ ] Manter `sanitize.py` como higiene, nao defesa principal

### SEC-012 - Rate limiting
- [ ] Limitar `/chat` por IP
- [ ] Retornar `429` com `Retry-After`
- [ ] Expor configuracao por ambiente

### SEC-013 - Confinamento no system prompt
- [ ] Endurecer prompt do dominio
- [ ] Cobrir fora de escopo, redefinicao e segredo
- [ ] Manter evals dedicados

## M4 - Git e CI/CD

### SEC-014 - Branch protection
- [ ] Exigir PR
- [ ] Exigir checks
- [ ] Bloquear push direto na `main`

### SEC-015 - CI com testes e gitleaks
- [ ] Rodar testes automatizados
- [ ] Rodar auditoria de segredos
- [ ] Bloquear merge quando falhar

## M5 - Docs e LGPD

### SEC-016 - Anonimizacao de dados
- [ ] Remover PII antes de ingestao
- [ ] Documentar processo
- [ ] Definir retencao

### SEC-017 - Runbook de incidentes
- [ ] Criar runbook publico sem detalhes sensiveis
- [ ] Manter detalhes operacionais em documento privado

### SEC-018 - Publicacao final
- [ ] Publicar politica publica de seguranca
- [ ] Revisar docs para versao community-safe
- [ ] Criar release de baseline

## Quadro semanal

| Issue | Titulo resumido | Responsavel | Status | Semana |
|---|---|---|---|---|
| SEC-001 | Rotacionar IP VPS | Silotto | Aberta | Hoje |
| SEC-002 | Fechar acesso externo ao banco | Alexandre | Aberta | Hoje |
| SEC-003 | Trocar credenciais expostas | Alexandre + Renan | Aberta | Hoje |
| SEC-004 | Configurar firewall | Silotto + Renan | Planejada | Semana 1 |
| SEC-005 | Docker rede interna | Alexandre + Renan | Planejada | Semana 1 |
| SEC-006 | Cloudflare + HTTPS | Silotto + Renan | Planejada | Semana 1 |
| SEC-007 | Usuario prod DB | Alexandre | Planejada | Semana 1 |
| SEC-008 | Backup automatico | Alexandre | Planejada | Semana 1 |
| SEC-009 | Auditoria Git | Renan | Planejada | Semana 1 |
| SEC-010 | API Key endpoints | Renan | Planejada | Semana 2 |
| SEC-011 | Confinamento por design | Renan + Juliano | Planejada | Semana 2 |
| SEC-012 | Rate limiting | Renan | Planejada | Semana 2 |
| SEC-013 | Confinamento no prompt | Renan + Juliano | Planejada | Semana 2 |
| SEC-014 | Branch protection | Renan | Planejada | Semana 2 |
| SEC-015 | CI/CD + gitleaks | Renan | Planejada | Semana 2 |
| SEC-016 | Anonimizacao LGPD | Juliano | Planejada | Semana 3 |
| SEC-017 | Runbook incidentes | Renan | Planejada | Semana 3 |
| SEC-018 | Publicacao final | Renan + Silotto | Planejada | Semana 3 |

## Nota publica

Documentos privados podem manter incidentes reais, identificadores do ambiente, inventario de VPS e detalhes operacionais. O repositório publico deve conter apenas a versao sanitizada e educacional do plano.
