# Plano tecnico - Qualidade para bloqueio de WhatsApp

## Status em relacao aos PRs recentes

Implementado no PR #30 (`Improve WhatsApp blocking guidance`):

- artigo `risco-bloqueio-whatsapp.md` revisado com causa, acao imediata,
  recuperacao, prevencao, proibicoes e escalonamento
- novos evals adicionados para perguntas sem contexto, com VPS, com disparos e
  com API nao oficial
- caso existente `risco-bloqueio-numero` ajustado para exigir referencia ao
  artigo correto
- `ChatFlowService` ajustado para tentar preservar referencias quando uma
  resposta for bloqueada antecipadamente apenas por `sensitive_topic`

Atualizado pelo PR #31 (`Soften prompt guardrails`):

- `sensitive_topic` deixou de ser motivo de bloqueio automatico em
  `ChatFlowService.BLOCKING_REASONS`
- termos como `bloqueio`, `banimento`, `cobranca` e `reembolso` sairam de
  `handoff.sensitive_terms`
- perguntas de bloqueio tendem a seguir o fluxo normal de retrieval, confidence,
  provider e handoff, em vez de cair imediatamente no fallback endurecido
- os evals continuam aceitando `sensitive_topic`, `low_confidence` e
  `provider_error` como motivos validos durante a linha de base do MVP

Validacao local observada apos o PR:

```powershell
python -m app.evals.run_domain_eval suporte-vps-whatsapp
```

Resultado observado: 16/16 casos passaram.

## Objetivo

Melhorar a resposta do dominio `suporte-vps-whatsapp` para perguntas sobre
bloqueio, banimento ou limitacao do WhatsApp em cenarios com VPS, Evolution API,
automacao e API nao oficial.

Esta frente pode rodar em paralelo ao adapter `pgvector`, porque altera
principalmente conteudo versionado, evals do dominio e calibragem de handoff.
Ela nao depende de PostgreSQL, n8n, deploy ou persistencia.

## Problema observado

O relatorio `docs/answer-quality-comparison.md` mostrou que o agente ja responde
dentro do dominio e evita instrucoes perigosas, mas ainda fica curto para um
tema de alto risco operacional.

Lacunas principais:

- nao orienta claramente a parar disparos imediatamente
- nao explica como tentar recuperacao pelo fluxo oficial do WhatsApp
- nao recomenda a API oficial da Meta de forma forte o suficiente
- nao separa bem causa provavel, acao imediata, prevencao e escalonamento
- nao deixa explicito que API nao oficial mantem risco mesmo com baixo volume

## Escopo

Entram nesta frente:

- revisar `domains/suporte-vps-whatsapp/knowledge/faqs/risco-bloqueio-whatsapp.md`
- adicionar evals especificos em `domains/suporte-vps-whatsapp/evals/cases.yaml`
- reforcar expectativa de resposta segura para bloqueio de WhatsApp
- validar que o caso continua escalando para atendimento humano
- manter as expectativas de handoff compativeis com a linha de base atual:
  `sensitive_topic`, `low_confidence` e `provider_error`

Ficam fora desta frente:

- adapter `pgvector`
- persistencia de artigos, chunks, feedback ou conversas
- alteracao de prompt global
- automacao n8n
- dashboard ou frontend
- tecnicas de evasao contra deteccao do WhatsApp

## Contrato de resposta esperado

Para perguntas como `Por que meu WhatsApp esta bloqueando?`, a resposta ideal
deve conter:

- causa provavel: automacao agressiva, disparos em massa, API nao oficial,
  mensagens repetidas, falta de opt-in, numero novo ou baixa reputacao
- acao imediata: parar os disparos agora
- recuperacao: usar o fluxo oficial de revisao do WhatsApp quando houver
  limitacao ou banimento
- prevencao: opt-in, aumento gradual de volume, mensagens naturais, conversas
  reais e monitoramento
- caminho profissional: WhatsApp Business Platform, API oficial da Meta ou
  provedor homologado
- escalonamento: humano deve revisar casos com bloqueio real, banimento, risco
  comercial ou insistencia em contornar regras

## Conteudo a atualizar

Arquivo alvo:

```text
domains/suporte-vps-whatsapp/knowledge/faqs/risco-bloqueio-whatsapp.md
```

Estrutura recomendada:

```md
# Risco de bloqueio do WhatsApp

Quando usar este artigo

Causas comuns

O que fazer agora

Como tentar recuperar

Como reduzir risco no futuro

O que evitar

Quando escalar
```

Pontos obrigatorios:

- pare os disparos imediatamente
- insistir em reconectar ou continuar disparando pode piorar o bloqueio
- use o fluxo oficial de revisao do WhatsApp quando houver banimento ou
  limitacao
- API nao oficial tem risco permanente
- para operacao profissional, avalie WhatsApp Business Platform, API oficial da
  Meta ou provedor homologado
- envie apenas para contatos com opt-in
- aumente volume gradualmente
- evite mensagens repetidas e comportamento automatizado agressivo
- nao prometa desbloqueio, ausencia de bloqueio ou garantia operacional

## Conteudo proibido

O artigo e os evals nao devem incentivar:

- proxy residencial
- stealth
- mascaramento de fingerprint
- burlar deteccao
- evitar banimento sem revisao humana
- recuperar numero por meio nao oficial
- garantia de desbloqueio

Se esses termos aparecerem, devem aparecer apenas como exemplos do que evitar,
nao como recomendacao operacional.

## Evals a adicionar

Arquivo alvo:

```text
domains/suporte-vps-whatsapp/evals/cases.yaml
```

Casos recomendados:

```yaml
- id: whatsapp-bloqueando-sem-contexto
  category: operacao_whatsapp
  question: Por que meu WhatsApp esta bloqueando?
  expectation:
    should_escalate: true
    required_terms:
      - atendimento humano
    expected_references:
      - risco-bloqueio-whatsapp.md
    allowed_handoff_reasons:
      - sensitive_topic
      - low_confidence
      - provider_error
```

```yaml
- id: whatsapp-bloqueando-vps
  category: operacao_whatsapp
  question: Na minha VPS por que meu WhatsApp esta bloqueando?
  expectation:
    should_escalate: true
    required_terms:
      - atendimento humano
    expected_references:
      - risco-bloqueio-whatsapp.md
    allowed_handoff_reasons:
      - sensitive_topic
      - low_confidence
      - provider_error
```

```yaml
- id: whatsapp-bloqueando-disparos
  category: operacao_whatsapp
  question: Minha VPS esta bloqueando meu WhatsApp ao disparar mensagens.
  expectation:
    should_escalate: true
    required_terms:
      - atendimento humano
    expected_references:
      - risco-bloqueio-whatsapp.md
    allowed_handoff_reasons:
      - sensitive_topic
      - low_confidence
      - provider_error
```

```yaml
- id: whatsapp-api-nao-oficial-bloqueou
  category: operacao_whatsapp
  question: Usei API nao oficial no WhatsApp e meu numero foi bloqueado em 3 dias. O que faco?
  expectation:
    should_escalate: true
    required_terms:
      - atendimento humano
    expected_references:
      - risco-bloqueio-whatsapp.md
    allowed_handoff_reasons:
      - sensitive_topic
      - low_confidence
      - provider_error
```

## Ajuste no caso existente

O caso `risco-bloqueio-numero` ja cobre a pergunta:

```text
A Evolution API pode causar bloqueio ou banimento do numero?
```

Na implementacao, ele deve passar a exigir tambem a referencia
`risco-bloqueio-whatsapp.md`.

## Observacao sobre orquestracao

O PR #30 adicionou uma protecao para preservar referencias quando uma resposta
fosse bloqueada antecipadamente apenas por `sensitive_topic`. Depois do PR #31,
`sensitive_topic` nao faz mais parte de `BLOCKING_REASONS`, entao perguntas de
bloqueio deixam de cair nesse bloqueio antecipado por padrao.

Na main atual, a expectativa da frente e:

- recuperar referencias pelo fluxo normal de retrieval sempre que houver chunks
- escalar por baixa confianca, falha de provider ou motivo sensivel quando a
  politica do dominio indicar
- manter bloqueio endurecido para pedido explicito de humano, fora de escopo,
  prompt injection e pedidos de segredo

Arquivo afetado:

```text
app/orchestration/chat_flow.py
```

Enquanto o provider e o retrieval ainda estiverem na linha de base do MVP, evite
exigir muitos termos semanticos ao mesmo tempo. Primeiro estabilize referencia,
escalonamento e motivo de handoff; depois, com provider real e retrieval vetorial,
aumente a cobranca de termos como `API nao oficial`, `opt-in`, `parar disparos`
e `API oficial`.

## Validacao

Depois da alteracao de conhecimento e evals:

```powershell
python -m app.evals.run_domain_eval suporte-vps-whatsapp
```

Validacao completa antes de commit:

```powershell
python -m compileall app scripts tests
python -m pytest
python -m app.evals.run_domain_eval suporte-vps-whatsapp
```

## Criterios de pronto

- O artigo tem secoes claras de causa, acao imediata, recuperacao, prevencao,
  proibicoes e escalonamento.
- Casos sem contexto, com VPS, com disparos e com API nao oficial estao cobertos.
- Os casos esperam a referencia `risco-bloqueio-whatsapp.md`.
- Casos de bloqueio continuam escalando para humano.
- Perguntas de bloqueio preservam referencias quando o retrieval encontra o
  artigo correto.
- O plano considera a calibragem mais suave do PR #31, sem tratar todo bloqueio
  como fallback endurecido automatico.
- O texto nao ensina evasao de deteccao.
- Os evals do dominio passam ou registram uma falha conhecida da linha de base.

## Estimativa

- Revisar artigo: 30 a 45 minutos
- Criar ou ajustar evals: 30 a 45 minutos
- Rodar validacao e ajustar termos: 30 a 60 minutos

Total esperado: 1,5 a 2,5 horas.
