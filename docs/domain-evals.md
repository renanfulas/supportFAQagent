# Calibragem de Dominio

Evals sao casos pequenos que ajudam a medir se o agente esta respondendo e escalando como esperado para um dominio.

Eles nao substituem teste unitario. Eles servem como um termometro de produto.

## Onde ficam

```text
domains/
  suporte-vps-whatsapp/
    evals/
      cases.yaml
      pgvector_gate.yaml
      pgvector_curated.yaml
      intake/
```

## Como rodar

```bash
python -m app.evals.run_domain_eval suporte-vps-whatsapp
```

Para o dominio comercial `vendas` (Servidor VPS e Hospedagem de Sites HostGator):

```bash
python -m app.evals.run_domain_eval vendas
python -m app.evals.run_domain_eval vendas --file evals/confinement/out_of_scope.yaml
python -m app.evals.run_domain_eval vendas --file evals/confinement/redefinition.yaml
python -m app.evals.run_domain_eval vendas --file evals/confinement/secrets.yaml
```

O metodo de interacao consultiva usado por esse dominio (rapport, descoberta,
recomendacao, objecao e fechamento, com escalonamento humano para etapas
sensiveis) esta na skill `supportfaq-vendas-closer` e ancorado em
`domains/vendas/knowledge/articles/metodo-de-venda-consultiva.md`.

Para os novos dominios em Fase 1, com base de conhecimento real e provider
`openai` (mesmo padrao deterministico dos dominios vivos). `suporte-hospedagem`
ja entra no roteador (`WHATSAPP_ROUTER_DOMAINS`); `suporte-vps` segue fora do
roteador por colisao de vocabulario com `suporte-vps-whatsapp` (ver
`docs/domain-architecture-roadmap.md`):

```bash
python -m app.evals.run_domain_eval suporte-hospedagem
python -m app.evals.run_domain_eval suporte-hospedagem --file evals/confinement/out_of_scope.yaml
python -m app.evals.run_domain_eval suporte-vps
python -m app.evals.run_domain_eval suporte-vps --file evals/confinement/out_of_scope.yaml
```

Para suites dedicadas de confinamento:

```bash
python -m app.evals.run_domain_eval suporte-vps-whatsapp --file evals/confinement/out_of_scope.yaml
python -m app.evals.run_domain_eval suporte-vps-whatsapp --file evals/confinement/redefinition.yaml
python -m app.evals.run_domain_eval suporte-vps-whatsapp --file evals/confinement/secrets.yaml
```

Para a futura suite opt-in de calibragem com `pgvector` e provider real:

```bash
python -m app.evals.run_domain_eval suporte-vps-whatsapp --file evals/pgvector_real.yaml
```

Para as suites atuais de calibragem com `pgvector`:

```bash
python -m app.evals.run_domain_eval suporte-vps-whatsapp --file evals/pgvector_gate.yaml
python -m app.evals.run_domain_eval suporte-vps-whatsapp --file evals/pgvector_curated.yaml
```

Essa suite nao deve entrar como gate obrigatorio de CI enquanto depender de
`DATABASE_URL`, provider externo e dados ingeridos no pgvector.

O comando retorna JSON com:

- total de casos
- quantidade aprovada
- quantidade com falha
- falhas por caso
- confianca
- motivos de escalonamento
- referencias usadas

## Contrato de um caso

```yaml
domain: suporte-vps-whatsapp
cases:
  - id: qrcode-whatsapp-nao-conecta
    category: operacao_whatsapp
    question: Quando tento conectar meu WhatsApp na Evolution, o QR Code nao abre.
    expectation:
      should_escalate: false
      required_terms:
        - mock provider
      expected_references:
        - qrcode-whatsapp.md
      allowed_handoff_reasons:
        - sensitive_topic
```

## Campos

- `id`: identificador curto e estavel.
- `category`: frente do produto, como `setup_tecnico`, `operacao_whatsapp`, `integracoes`.
- `question`: pergunta real ou adaptada de usuario.
- `should_escalate`: se o caso deve ir para humano.
- `required_terms`: termos que precisam aparecer na resposta.
- `expected_references`: trechos esperados nas fontes recuperadas.
- `allowed_handoff_reasons`: motivos de escalonamento aceitos, quando aplicavel.

## Como usar no MVP

No estado atual, os evals locais devem continuar deterministas e nao depender de provider real ou credenciais privadas. Por isso alguns casos validam comportamento estrutural:

- se recuperou a referencia correta
- se escalou quando deveria
- se manteve motivo de handoff esperado
- se preservou fallback seguro quando o provider real nao pode responder

Como o retrieval lexical ainda e simples, alguns casos podem esperar `low_confidence` mesmo quando ha documentos relacionados. Isso e uma linha de base do MVP, nao o comportamento final desejado.

Quando provider real e pgvector estiverem calibrados em ambiente privado, estes casos devem evoluir para validar conteudo mais forte sem quebrar o gate deterministico local.

## Suites pgvector/provider real

Estado atual:

- `evals/pgvector_gate.yaml` e a suite curta de gate do MVP
- `evals/pgvector_curated.yaml` e a suite ampla de diagnostico e calibracao
- `evals/intake/` contem o banco sintetico de perguntas para cobertura
- `evals/intake/hostgator-categories-mapping.md` registra o mapeamento das
  categorias reais do suporte HostGator (dentro vs fora do escopo deste
  dominio) usado para gerar `vps_support_faq_hostgator_real.yaml` e os novos
  casos de `evals/confinement/out_of_scope.yaml`
- `evals/pgvector_real.yaml` continua opcional para uma rodada futura com
  perguntas anonimas reais

A suite `evals/pgvector_real.yaml` deve ser criada somente depois do relatorio
anonimo real chegar. Ate la, use `evals/pgvector_real.example.yaml` apenas como
template.

Objetivo dessa suite:

- validar perguntas anonimas parecidas com o suporte real
- medir se o pgvector recupera as referencias esperadas
- medir se `confidence` e `handoff_reasons` estao coerentes
- garantir que `error_code` fique ausente em casos saudaveis
- acompanhar `RETRIEVAL_BACKEND=pgvector` como default do staging e detectar
  regressao antes de manter ou expandir a promocao

Ela deve ser rodada de forma opt-in em ambiente privado com:

- `DATABASE_URL` configurado
- provider real configurado, como `OPENAI_API_KEY`
- conhecimento do dominio ingerido no pgvector

O processo de entrada dos casos esta em
`docs/runbooks/anonymous-eval-intake.md`.

## Casos de seguranca

Para a trilha `SEC-013`, adicione tambem casos que exercitem:

- pedido explicito de atendimento humano
- tentativa de obter senha, token, chave ou dado sensivel
- tentativa de ignorar instrucoes, revelar prompt ou contornar regras
- pergunta fora do escopo que precise recusa segura ou escalonamento

No estado atual do MVP, esses casos ainda validam principalmente:

- se houve escalonamento
- se o motivo de handoff esperado apareceu
- se o retrieval caiu em uma referencia coerente

Quando o provider real e os evals de resposta evoluirem, essa mesma trilha deve passar a cobrar recusa semantica mais forte.

Na trilha `SEC-013`, mantenha suites separadas para:

- fora do escopo
- redefinicao de identidade ou papel
- pedido de prompt, segredo, token, chave ou credencial

## Quando adicionar casos

Adicione um caso quando:

- uma duvida aparecer mais de uma vez no suporte
- uma resposta errada gerar risco operacional
- uma mudanca de prompt/retrieval alterar comportamento esperado
- um humano precisar corrigir frequentemente o mesmo tema

## Boas praticas

- Prefira perguntas parecidas com mensagens reais.
- Evite casos enormes demais.
- Mantenha expectativas simples no inicio.
- Nao coloque PII, telefones reais, tokens, senhas ou dados sensiveis.
- Nao coloque IP publico, dominio de cliente, payload bruto, header, log cru ou
  qualquer identificador reversivel.
- Se um caso falhar por falta de artigo, primeiro melhore a base de conhecimento.
