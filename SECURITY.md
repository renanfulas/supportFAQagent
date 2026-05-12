# 🛡️ Política de Segurança — supportFAQagent

## Versão suportada

| Versão | Suporte de segurança |
|--------|----------------------|
| `main` (MVP) | ✅ Ativa |
| branches `feat/*` | ⚠️ Em desenvolvimento |

---

## Reportar uma vulnerabilidade

**Não abra uma Issue pública para reportar vulnerabilidades.**

Se você encontrou uma falha de segurança neste projeto, entre em contato de forma privada:

- Abra um **GitHub Security Advisory** (aba Security → Advisories → New draft)
- Ou envie mensagem direta para o mantenedor principal: [@renanfulas](https://github.com/renanfulas)

### O que incluir no relatório

- Descrição clara da vulnerabilidade
- Passos para reproduzir
- Impacto potencial (o que um atacante poderia fazer)
- Sugestão de correção, se tiver

### O que esperar

- Confirmação de recebimento em até **48 horas**
- Avaliação de severidade em até **5 dias úteis**
- Correção publicada em até **30 dias** para severidade alta/crítica

---

## Escopo deste projeto

Este repositório cobre:

- API FastAPI (`app/`)
- Pipeline RAG e ingestão (`app/ingestion/`, `app/retrieval/`)
- Configuração de domínios (`domains/`)
- Scripts operacionais (`scripts/`)
- Integrações: Evolution API, n8n, PostgreSQL/pgvector

---

## Práticas de segurança do time

- Nenhuma chave de API, senha ou IP é commitado no repositório
- O arquivo `.env` está no `.gitignore` e nunca é versionado
- Todo acesso ao banco de produção é feito via túnel SSH
- Pull Requests na `main` exigem revisão de pelo menos 1 membro do time
- Vulnerabilidades em dependências são verificadas automaticamente pelo CI

---

## Créditos

Agradecemos a qualquer pessoa que reporte vulnerabilidades de forma responsável.
Contribuidores de segurança serão reconhecidos no CHANGELOG, com permissão.

---

*supportFAQagent — Open Source patrocinado por HostGator*
*Mantenedor: Renan Junior | Comunidade: Alexandre Madeira, Juliano Barreto, Silotto*
