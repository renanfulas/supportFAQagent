# Contrato de Dominio

Um dominio define como o agente deve atuar em uma area especifica, sem mudar o motor compartilhado em `app/`.

Exemplos de dominios futuros:

- `suporte-vps-whatsapp`
- `vendas`
- `onboarding`
- `financeiro`

## Arquivo principal

Cada dominio precisa ter:

```text
domains/
  nome-do-dominio/
    domain.yaml
    knowledge/
    prompts/
```

O `domain.yaml` e o contrato minimo do dominio.

## Campos principais

```yaml
contract_version: 1
name: vendas
display_name: Suporte de Vendas
description: Agente para duvidas comerciais e qualificacao inicial.
owner: Comercial
default_language: pt-BR

behavior:
  persona: consultor de vendas claro e consultivo
  primary_goal: ajudar leads com duvidas comerciais simples
  answer_guidelines:
    - qualifique antes de sugerir plano
    - seja objetivo e evite promessas comerciais absolutas
  out_of_scope:
    - suporte tecnico profundo
    - negociacoes contratuais sensiveis

routing:
  keywords:
    - preco
    - plano
    - contratar

response:
  tone: simples
  max_context_chunks: 5
  max_answer_length: short
  no_context_message: Nao encontrei contexto suficiente neste dominio. O ideal e escalar para humano.
  provider_error_message: Nao consegui gerar uma resposta automatica agora. Vou sinalizar escalonamento.

handoff:
  confidence_threshold: 0.7
  escalate_on:
    - low_confidence
    - explicit_human_request
  explicit_human_phrases:
    - falar com humano
    - atendente
  sensitive_terms:
    - contrato
    - reembolso
  escalation_rules:
    - reason: operational_risk
      terms:
        - bloqueio
        - banimento

knowledge:
  sources:
    - knowledge/faqs
    - knowledge/articles

llm:
  provider: mock
  model: mock-model
  embedding_model: mock-embedding

embedding:
  provider: openai
  model: text-embedding-3-small
  dimensions: 1536

feature_flags:
  context_aware_scope: false
```

## Regras simples

- `name` deve ser igual ao nome da pasta do dominio.
- Dominios invalidos nao aparecem em `GET /domains`.
- Conteudo especifico do setor deve ficar em `domains/<dominio>/knowledge`.
- Regra reutilizavel entre setores deve ficar em `app/`.
- Comece com `provider: mock` antes de ligar provider real.
- Ajuste `confidence_threshold` so depois de observar conversas reais.
- `feature_flags` e um mapa opcional `nome -> on/off` por dominio, default vazio
  (toda flag desligada). Serve para ligar uma mudanca de comportamento atras de
  flag escopada a um dominio, sem variavel de ambiente global. Leia no codigo com
  `domain.is_flag_enabled("<flag>")`, que devolve `False` para flag nao declarada.

## Como criar um novo dominio

1. Copie `domains/suporte-vps-whatsapp` para uma nova pasta.
2. Renomeie a pasta e o campo `name` para o novo dominio.
3. Atualize `display_name`, `description`, `owner` e `behavior`.
4. Troque os artigos em `knowledge/`.
5. Rode `python -m pytest`.
6. Teste `GET /domains` e `POST /chat` usando o novo dominio.

## O que o contrato influencia hoje

- Prompt base do agente.
- Persona e objetivo principal.
- Diretrizes de resposta.
- Itens fora do escopo.
- Quantidade de chunks recuperados.
- Mensagens padrao de falta de contexto ou erro de provider.
- Threshold e gatilhos de escalonamento.
- Regras configuraveis de escalonamento por termos do dominio, sem hardcode no motor compartilhado.
