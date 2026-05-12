# 📚 Índice de Documentos — supportFAQagent Security Pack
**Guia de conteúdo, aplicação e checklist de implementação**
**Versão 1.1 — Maio/2026**

---

## 1. ÍNDICE GERAL DOS DOCUMENTOS

| # | Documento | Onde fica no repo | Para quem é |
|---|---|---|---|
| D1 | `SECURITY.md` | raiz do repositório | Comunidade / contribuidores externos |
| D2 | `vps-security-plan.md` | `docs/security/` | Time técnico (Renan, Alexandre, Juliano, Silotto) |
| D3 | `llm-confinement.md` | `docs/security/` | Renan + Juliano (arquitetura do agente) |
| D4 | `implementation-tracking.md` | `docs/security/` | Todo o time — acompanhamento semanal |
| D5 | `git-commit-guide.md` | `docs/security/` | Todo o time — antes de abrir qualquer PR |
| D6 | `ESTRUTURA-E-COMMITS.md` | raiz do repositório | Renan — guia de onde commitar cada arquivo |
| D7 | `security-incident.md` | `.github/ISSUE_TEMPLATE/` | Qualquer pessoa que encontre uma falha |

---

## D1 — SECURITY.md
**Onde:** raiz do repositório
**Tamanho:** 66 linhas

### O que contém
Política pública de segurança do projeto. É o arquivo que o GitHub exibe automaticamente na aba Security do repositório. Cobre: como reportar uma vulnerabilidade sem expor publicamente, o que esperar em tempo de resposta, o escopo do projeto e as práticas básicas do time.

### Para que serve na prática
Qualquer pessoa que encontrar uma falha no projeto — seja da comunidade HostGator, seja um contribuidor externo — sabe exatamente o que fazer. Sem este arquivo, a tendência é abrir uma Issue pública com detalhes sensíveis expostos.

### Quando usar
Commitar uma vez na raiz. Não muda frequentemente. Revisar somente se mudar o time de mantenedores ou o canal de contato.

---

## D2 — vps-security-plan.md
**Onde:** `docs/security/`
**Tamanho:** ~680 linhas

### O que contém
O plano completo de segurança em 9 camadas, construído a partir das conversas do grupo:

| Camada | Tema | Responsável principal |
|---|---|---|
| 1 | Firewall UFW da VPS | Silotto + Renan |
| 2 | Isolamento Docker (redes internas) | Alexandre + Renan |
| 3 | Cloudflare e HTTPS | Silotto + Renan |
| 4 | Banco de dados (usuários, backup, criptografia) | Alexandre |
| 5 | Gerenciamento de segredos e `.env` | Renan |
| 6 | Segurança da API FastAPI | Renan |
| 7 | Segurança do LLM e RAG (confinamento por design) | Renan + Juliano |
| 8 | Git e CI/CD seguro | Renan |
| 9 | Observabilidade e auditoria | Renan |

Inclui código funcional para cada camada: configuração UFW, docker-compose seguro, SQL de usuários, scripts de backup, middleware FastAPI, system prompt confinado.

### Para que serve na prática
Referência técnica durante a implementação. Cada dev consulta a seção da sua responsabilidade antes de abrir o PR correspondente.

### Quando usar
Consultar antes de implementar cada Issue SEC-001 a SEC-018. Atualizar quando houver mudança de stack (ex: trocar Cloudflare por outro provider).

---

## D3 — llm-confinement.md
**Onde:** `docs/security/`
**Tamanho:** ~180 linhas

### O que contém
Decisão arquitetural registrada: por que o projeto adotou confinamento por design em vez de detecção de prompt injection. Explica o problema do labirinto reativo, onde a segurança do LLM vive na arquitetura (no `domain.yaml`, não no `sanitize.py`), o papel correto do `sanitize.py` como higiene de input, o modelo de evals de confinamento e como adicionar novos domínios sem quebrar a segurança.

### Para que serve na prática
Documento de referência para qualquer contribuidor que tentar "melhorar a segurança" adicionando filtros de palavras no código — este documento explica por que essa abordagem está descartada e qual é a correta. Evita que a decisão se perca quando o time crescer.

### Quando usar
Renan e Juliano consultam na implementação das SEC-011 e SEC-013. Todo novo contribuidor lê antes de tocar em qualquer arquivo dentro de `domains/` ou `app/orchestration/`.

---

## D4 — implementation-tracking.md
**Onde:** `docs/security/`
**Tamanho:** ~450 linhas

### O que contém
18 Issues detalhadas (SEC-001 a SEC-018) organizadas em 6 milestones. Cada Issue tem: contexto extraído das conversas do grupo, lista de tarefas com checkboxes, responsável, e Definition of Done. Inclui quadro de acompanhamento semanal com status de cada Issue.

### Estrutura das milestones

| Milestone | Issues | Prazo |
|---|---|---|
| M0 — Incidentes Imediatos | SEC-001, 002, 003 | Hoje |
| M1 — Infraestrutura VPS | SEC-004, 005, 006 | Semana 1 |
| M2 — Banco e Segredos | SEC-007, 008, 009 | Semana 1 |
| M3 — API e LLM | SEC-010, 011, 012, 013 | Semana 2 |
| M4 — Git e CI/CD | SEC-014, 015 | Semana 2 |
| M5 — Docs e LGPD | SEC-016, 017, 018 | Semana 3 |

### Para que serve na prática
É o board de trabalho do time. Cada membro abre este arquivo, vê as Issues da sua milestone, implementa, e atualiza o quadro de status quando fizer merge do PR.

### Quando usar
Abrir toda semana. Atualizar o status (⚪ → 🟡 → 🟢) a cada PR mergeado. Apresentar no Meetup de quinta como visão geral do progresso.

---

## D5 — git-commit-guide.md
**Onde:** `docs/security/`
**Tamanho:** ~260 linhas

### O que contém
Convenção de nomenclatura de branches (`security/SEC-XXX-descricao`), padrão de mensagens de commit, template de PR com checklist de segurança, lista de labels necessárias no GitHub, e a sequência exata de commits mapeada por membro do time (Renan, Alexandre, Juliano, Silotto). Inclui o commit de tag final `v0.1.0-security-baseline`.

### Para que serve na prática
Garante que o histórico Git do projeto de segurança seja rastreável. Qualquer pessoa pode ver no log que `security(SEC-002)` resolveu o problema da porta 5432, quando foi mergeado e por quem. Isso é a auditoria do plano.

### Quando usar
Antes de abrir qualquer branch de segurança. O template de PR deve ser colado no GitHub ao abrir cada PR das Issues SEC-001 a SEC-018.

---

## D6 — ESTRUTURA-E-COMMITS.md
**Onde:** raiz do repositório (uso interno do time)
**Tamanho:** ~155 linhas

### O que contém
Mapa completo de onde cada arquivo vai no repositório, tabela de status (o que já existe vs. o que criar), a ordem cronológica de commits por prioridade (hoje, semana 1, semana 2, semana 3) e o commit único para subir todos os documentos de segurança de uma vez.

### Para que serve na prática
É o guia de navegação do Renan para executar o plano. Responde: "qual arquivo eu crio agora, onde ele vai, e o que eu escrevo no commit?"

### Quando usar
Renan usa como checklist operacional para subir os documentos no repositório. Após todos os documentos commitados, pode ser arquivado ou removido — seu papel é de guia de onboarding do pacote de segurança.

---

## D7 — security-incident.md (Issue Template)
**Onde:** `.github/ISSUE_TEMPLATE/`
**Tamanho:** ~55 linhas

### O que contém
Template de Issue do GitHub para reportar incidentes de segurança. Cobre: tipo de incidente (credencial exposta, porta aberta, prompt injection, LGPD), severidade estimada, descrição, passos para reproduzir, impacto potencial e milestone relacionada. Inclui aviso para não abrir Issue pública em casos críticos — usar Security Advisory.

### Para que serve na prática
Padroniza como o time e a comunidade reportam problemas. Evita que alguém abra uma Issue dizendo apenas "tem um bug de segurança" sem contexto, ou pior, que poste credenciais expostas publicamente.

### Quando usar
Disponível automaticamente no GitHub quando qualquer usuário clicar em "New Issue" no repositório.

---

---

## 2. CHECKLIST — CRIAÇÃO E ACESSO AO BANCO DE DADOS

> **Contexto:** O banco `supportfaqagent` foi criado por Alexandre Madeira na VPS.
> O usuário `renan_faq` tem acesso restrito ao banco.
> Esta checklist cobre os próximos passos para o time acessar com segurança.

---

### ⚠️ PASSO 0 — Trocar a senha atual (IMEDIATO)

A senha atual circulou em canal aberto. Deve ser trocada antes de qualquer outro passo.

```sql
-- Conectar como postgres admin na VPS e executar:
ALTER USER renan_faq WITH PASSWORD 'NOVA_SENHA_GERADA_COM_openssl_rand_-base64_32';
```

**Tempo:** 5 minutos
**Responsável:** Alexandre Madeira
**Comunicar a nova senha:** somente via DM direta, nunca em grupo

---

### PASSO 1 — Confirmar acesso local via túnel SSH

Cada dev testa a conexão via túnel antes do próximo passo.

```bash
# Terminal 1 — abrir o túnel
ssh -L 5432:localhost:5432 usuario@IP_DA_VPS

# Terminal 2 — conectar ao banco
psql -h localhost -p 5432 -U renan_faq -d supportfaqagent
```

- [ ] Renan testou conexão via túnel
- [ ] Alexandre testou conexão via túnel
- [ ] Juliano testou conexão via túnel (quando entrar no acesso)

**Tempo estimado:** 15 minutos por dev
**Bloqueante para:** iniciar desenvolvimento local com banco real

---

### PASSO 2 — Criar usuário de produção com privilégios mínimos (SEC-007)

O `renan_faq` foi criado para desenvolvimento. Para produção, criar um usuário separado.

```sql
-- Executar no banco como admin
CREATE USER supportfaq_prod WITH PASSWORD 'GERAR_COM_openssl';
GRANT CONNECT ON DATABASE supportfaqagent TO supportfaq_prod;
GRANT USAGE ON SCHEMA public TO supportfaq_prod;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO supportfaq_prod;
REVOKE DELETE ON TABLE domains FROM supportfaq_prod;
```

- [ ] Usuário `supportfaq_prod` criado
- [ ] Script commitado em `migrations/002_production_users.sql`
- [ ] `.env.example` atualizado com as variáveis de ambiente corretas

**Tempo estimado:** 30 minutos
**Responsável:** Alexandre Madeira
**Issue:** SEC-007

---

### PASSO 3 — Configurar `.env` local de cada dev

Cada dev configura o próprio `.env` com as credenciais corretas para desenvolvimento.

```bash
# .env local (nunca commitar)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=supportfaqagent
DB_USER=renan_faq
DB_PASSWORD=SENHA_RECEBIDA_VIA_DM
```

- [ ] Renan configurou `.env` local
- [ ] Alexandre configurou `.env` local
- [ ] Juliano configurou `.env` local
- [ ] Verificar que `.env` está no `.gitignore` (`git check-ignore -v .env`)

**Tempo estimado:** 10 minutos por dev
**Bloqueante para:** rodar a API localmente

---

### PASSO 4 — Rodar os testes de banco existentes

Os 5 testes SQL criados por Alexandre validam que o banco está correto.

```bash
# Na raiz do projeto, via script bash (conforme combinado com Renan)
bash scripts/run_db_tests.sh
```

Testes cobertos:
- `test_01_extensions.sql` — pgvector e pgcrypto habilitados
- `test_02_schema.sql` — tabelas e campos corretos
- `test_03_idempotency.sql` — mesmo conteúdo não duplica
- `test_04_vector_search.sql` — busca top-k por domínio
- `test_05_isolation.sql` — domínio A não vaza para domínio B

- [ ] Todos os 5 testes passam na VPS
- [ ] Todos os 5 testes passam localmente (via túnel)

**Tempo estimado:** 20 minutos
**Responsável:** Alexandre Madeira + Renan (revisão)
**Issue:** validação da SEC-005

---

### PASSO 5 — Documentar o mapeamento de acesso ao banco

Registrar no repositório quem tem acesso, como e por quê.

Criar `docs/infrastructure/database-access.md` com:
- Stack: PostgreSQL 16 + pgvector + pgcrypto
- Como conectar (via túnel SSH — sem acesso direto externo)
- Usuários existentes e seus papéis
- Como solicitar acesso para novo dev (processo via DM)

- [ ] Documento criado e commitado
- [ ] Silotto revisou (será a VPS definitiva da HostGator)

**Tempo estimado:** 20 minutos
**Responsável:** Alexandre Madeira
**Issue:** SEC-007 (parte de docs)

---

### PASSO 6 — Migrar banco para a VPS da HostGator

Quando a VPS da HostGator ficar disponível (Silotto confirmou para hoje/amanhã), migrar o banco atual.

```bash
# Exportar da VPS atual do Alexandre
pg_dump -U postgres supportfaqagent > supportfaqagent_backup.sql

# Importar na VPS da HostGator (após Silotto confirmar acesso)
psql -h IP_VPS_HG -U postgres -d supportfaqagent < supportfaqagent_backup.sql
```

- [ ] VPS da HostGator recebida (aguardando Silotto)
- [ ] Banco exportado da VPS atual
- [ ] Banco importado na VPS da HostGator
- [ ] Testes SQL rodados na VPS nova
- [ ] Devs atualizam `.env` com novo host

**Tempo estimado:** 1 hora (inclui testes)
**Responsável:** Alexandre + Silotto
**Bloqueante para:** deploy do backend na VPS definitiva

---

### RESUMO — Previsão de tempo total

| Passo | Descrição | Tempo | Quando |
|---|---|---|---|
| 0 | Trocar senha exposta | 5 min | **Agora** |
| 1 | Testar acesso via túnel SSH | 15 min/dev | **Hoje** |
| 2 | Criar usuário de produção | 30 min | Hoje |
| 3 | Configurar `.env` local | 10 min/dev | Hoje |
| 4 | Rodar testes SQL | 20 min | Hoje |
| 5 | Documentar acesso ao banco | 20 min | Semana 1 |
| 6 | Migrar para VPS HostGator | 1h | Quando VPS chegar |

**Total estimado: ~3 horas distribuídas entre Alexandre, Renan e Silotto**
**Apresentar no Meetup de quinta:** passos 0 a 4 já concluídos ✅

---

*Documento gerado para o time supportFAQagent*
*Senhas e credenciais nunca são incluídas em documentos do repositório*
