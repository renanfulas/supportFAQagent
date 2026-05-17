# Plano de Seguranca da VPS - supportFAQagent
**Versao publica e community-safe**

Este documento descreve a arquitetura de seguranca recomendada para uma VPS que hospeda o projeto, sem expor incidentes reais, IPs, hostnames, credenciais ou detalhes operacionais do ambiente do time.

## Contexto da infraestrutura

Stack de referencia:

| Componente | Tecnologia |
|---|---|
| Provedor VPS | VPS Linux compativel |
| Containers | Docker |
| Banco de dados | PostgreSQL + extensao vetorial |
| Backend | FastAPI |
| Automacao externa | n8n |
| Protecao de borda | Proxy reverso e CDN |

## Incidentes que este plano ajuda a evitar

- exposicao publica de IP ou painel administrativo
- porta do banco aberta para internet
- credenciais compartilhadas em canais inseguros
- segredos versionados por engano
- prompt injection e uso fora do escopo do agente

## Camada 1 - Firewall

Recomendacao minima:

- SSH: liberar apenas para IPs autorizados
- HTTP e HTTPS: liberados para o mundo quando necessario
- Banco, paineis e portas internas: fechados por padrao
- portas temporarias de debug, como `8081`, nao devem ficar abertas para a internet

Checklist:

- [ ] politica default deny incoming
- [ ] acesso administrativo restrito
- [ ] nenhuma porta interna/debug exposta publicamente sem justificativa temporaria
- [ ] remover regras antigas de allow para `8081/tcp` quando a validacao terminar
- [ ] revisao periodica das regras

## Camada 2 - Docker e isolamento interno

- banco sem exposicao direta no host
- API e automacoes na mesma rede interna quando necessario
- servicos administrativos apenas por tunel ou proxy autenticado

## Camada 3 - Borda e HTTPS

- usar proxy/CDN para mascarar IP real
- forcar HTTPS
- aplicar rate limit de borda no endpoint de chat

## Camada 4 - Banco de dados

- usuario de aplicacao com privilegios minimos
- usuario somente leitura para analise ou evals
- backup automatico com restore testado
- acesso remoto apenas por tunel ou rede privada

## Camada 5 - Segredos

Regras publicas:

- `.env` nunca entra no Git
- segredos nao sao compartilhados em grupo
- producao usa credenciais separadas de desenvolvimento
- placeholders de exemplo podem existir, segredos reais nao
- qualquer credencial compartilhada em conversa operacional deve ser tratada
  como exposta e entrar em fila de rotacao
- relatorios publicos devem registrar apenas status de rotacao, nunca valores,
  usuarios, hostnames, IPs ou canais privados

## Camada 6 - API

Controles minimos:

- autenticacao por API key nos endpoints sensiveis
- rate limiting
- validacao de payload
- headers de seguranca HTTP

## Camada 7 - LLM e RAG

Princípio:

- seguranca por confinamento de dominio
- `sanitize.py` apenas como higiene de entrada
- prompt e `domain.yaml` como contrato principal de comportamento

## Camada 8 - Git e CI/CD

- branch protection na `main`
- CI com testes e auditoria de segredos
- revisao antes de merge

## Camada 9 - Observabilidade e auditoria

- `request_id` em respostas e logs
- preservacao de `handoff_reasons`, `error_code` e `references`
- logs sem PII, token, senha ou segredo
- logs e relatorios nao devem incluir prompt completo, resposta completa,
  pergunta original com identificador reversivel, payload bruto, headers ou
  stack traces com detalhes de ambiente

## Checklist pre-deploy

- [ ] IP real nao fica exposto publicamente
- [ ] banco nao aceita conexao externa direta
- [ ] segredos fora do Git
- [ ] credenciais compartilhadas em conversas operacionais foram rotacionadas
- [ ] autenticação por API key ativa
- [ ] rate limit ativo
- [ ] confinamento do agente validado
- [ ] backups configurados
- [ ] HTTPS ativo
- [ ] runbooks e relatorios revisados para nao conter logs crus, secrets ou PII

## Nota publica

Esta versao serve para comunidade e documentacao aberta. Runbooks com IPs reais, nomes de usuario, inventario de ambiente, regras detalhadas de firewall e incidentes concretos devem ficar em armazenamento privado fora do GitHub publico.
