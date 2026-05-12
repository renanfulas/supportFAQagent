---
name: "🛡️ Incidente de Segurança"
about: "Reportar um incidente, vulnerabilidade ou problema de segurança"
title: "[SEC] "
labels: ["security"]
assignees: ["renanfulas"]
---

## ⚠️ Antes de preencher

> Se esta vulnerabilidade expõe dados de usuários ou credenciais de produção,
> **não preencha esta Issue pública**.
> Abra um [GitHub Security Advisory](../../security/advisories/new) ou contate @renanfulas por DM.

---

## Tipo de incidente

- [ ] Credencial exposta (senha, API key, token)
- [ ] Porta ou serviço exposto indevidamente
- [ ] Prompt injection detectado em produção
- [ ] Vulnerabilidade em dependência
- [ ] Dado pessoal exposto (LGPD)
- [ ] Falha de autenticação na API
- [ ] Outro: ___________

## Severidade estimada

- [ ] 🔴 Crítico — sistema comprometido ou dado exposto agora
- [ ] 🟠 Alto — risco imediato se não corrigido
- [ ] 🟡 Médio — risco controlado, correção na próxima sprint
- [ ] 🟢 Baixo — melhoria preventiva

## Descrição

<!-- O que aconteceu? Onde? Quando foi descoberto? -->

## Como reproduzir (se aplicável)

1.
2.
3.

## Impacto potencial

<!-- O que um atacante poderia fazer com essa falha? -->

## Sugestão de correção

<!-- Se tiver ideia de como corrigir, descreva aqui -->

## Milestone relacionada

- [ ] M0 — Incidentes Imediatos
- [ ] M1 — Infraestrutura VPS
- [ ] M2 — Banco e Segredos
- [ ] M3 — API e LLM
- [ ] M4 — Git e CI/CD
- [ ] M5 — Docs e LGPD
