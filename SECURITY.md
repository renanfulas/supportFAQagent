# Politica de Seguranca - supportFAQagent

## Versao suportada

| Versao | Suporte de seguranca |
| --- | --- |
| `main` (MVP) | Ativa |
| branches de trabalho | Em desenvolvimento |

## Reportar uma vulnerabilidade

Nao abra uma Issue publica para reportar vulnerabilidades.

Se voce encontrou uma falha de seguranca neste projeto, entre em contato de forma privada:

- Abra um GitHub Security Advisory na aba Security do repositorio.
- Ou envie mensagem direta para o mantenedor principal: [@renanfulas](https://github.com/renanfulas).

### O que incluir no relatorio

- Descricao clara da vulnerabilidade.
- Passos para reproduzir.
- Impacto potencial.
- Sugestao de correcao, se tiver.

### O que esperar

- Confirmacao de recebimento em ate 48 horas.
- Avaliacao de severidade em ate 5 dias uteis.
- Correcao publicada em ate 30 dias para severidade alta ou critica, quando confirmada.

## Escopo deste projeto

Este repositorio cobre:

- API FastAPI (`app/`).
- Pipeline RAG e ingestao (`app/ingestion/`, `app/retrieval/`).
- Configuracao de dominios (`domains/`).
- Scripts operacionais (`scripts/`).
- Integracoes planejadas ou em evolucao documentadas no repositorio.

## Automacao atual

O repositorio passa a ter GitHub Actions para CI e checks basicos de seguranca:

- `.github/workflows/ci.yml` roda em pull requests e pushes para `main`, compila `app`, `tests` e `scripts`, e executa `pytest`.
- `.github/workflows/security.yml` roda em pull requests, pushes para `main` e semanalmente, com Gitleaks para secrets e `pip-audit` para dependencias Python.

Essas verificacoes reduzem risco, mas nao substituem revisao humana, rotacao de credenciais quando necessario, nem hardening do ambiente de producao.

## Praticas de seguranca do time

- Chaves de API, senhas, tokens e dados sensiveis nao devem ser commitados.
- O arquivo `.env` deve permanecer fora do versionamento.
- Pull Requests para `main` devem ser revisados antes do merge.
- Mudancas que afetem dados sensiveis, logs, credenciais, LLM, RAG ou integracoes externas devem explicar riscos e validacoes na PR.

## Hardening do canal WhatsApp / Hermes (piloto)

O bot conversacional de WhatsApp roda por uma ponte nao-oficial (bridge Baileys do
Hermes) com forward do inbound para `POST /integrations/hermes/chat/webhook`.

### Ja aplicado

- Webhook interno protegido por HMAC (`HERMES_CHAT_FORWARD_SECRET`) + janela de
  replay de 300s e limite de corpo (256 KB).
- Webhook rejeita (404) qualquer requisicao com header de proxy
  (`X-Forwarded-For`/`X-Real-IP`/`X-Forwarded-Host`): so o bridge local alcanca.
- nginx tambem nega publicamente `^~ /integrations/` e `^~ /internal/` (defesa em
  profundidade; o bridge usa `127.0.0.1:8000` direto, sem passar pelo nginx).
- Segredo do forward de chat segregado do segredo de OTP (`HERMES_WEBHOOK_SECRET`).
- Cap de mensagens por requisicao e rate limit por numero
  (`WHATSAPP_CHAT_RATE_LIMIT_PER_MINUTE`, padrao 20) para conter custo e ban.
- Logs do canal sem PII: apenas `request_id`, contadores e hashes.

### Follow-ups de seguranca em aberto

- Rotacionar a senha root da VPS (foi exposta em canal de chat operacional).
- Revisar/remover chaves SSH operacionais temporarias quando nao forem mais
  necessarias (ex.: `claude-code-supportfaq-vps`).
- Assinar o `X-Webhook-Timestamp` dentro do HMAC do forward (hoje a assinatura
  cobre so o body); reduz replay caso o endpoint deixe de ser localhost-only.
- Teto global de custo/volume no canal (o rate limit atual e por numero; uma
  multidao de numeros distintos nao e capada).
- Paridade do rate limit no transporte Meta quando o canal Meta for ativado.

### Caveat: ativacao do Meta WhatsApp e o deny do nginx

O webhook do Meta (`/integrations/meta/whatsapp/webhook`) e chamado externamente
pelos servidores da Meta. Como o nginx hoje nega `^~ /integrations/` publicamente,
ao ativar o Meta sera necessario abrir uma excecao apenas para esse path (o Hermes
nao precisa, pois e localhost direto). A escala publica de verdade deve migrar do
bridge nao-oficial para a Meta WhatsApp Cloud API para reduzir risco de banimento.

## Creditos

Agradecemos a qualquer pessoa que reporte vulnerabilidades de forma responsavel. Contribuidores de seguranca podem ser reconhecidos com permissao.

supportFAQagent - Open Source patrocinado por HostGator
Mantenedor: Renan Junior | Comunidade: Alexandre Madeira, Juliano Barreto, Silotto
