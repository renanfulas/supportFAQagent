# Calibragem de Dominio

Evals sao casos pequenos que ajudam a medir se o agente esta respondendo e escalando como esperado para um dominio.

Eles nao substituem teste unitario. Eles servem como um termometro de produto.

## Onde ficam

```text
domains/
  suporte-vps-whatsapp/
    evals/
      cases.yaml
```

## Como rodar

```bash
python -m app.evals.run_domain_eval suporte-vps-whatsapp
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

No estado atual, o provider padrao ainda e mock. Por isso alguns casos validam comportamento estrutural:

- se recuperou a referencia correta
- se escalou quando deveria
- se manteve motivo de handoff esperado
- se respondeu pelo caminho do provider mock

Como o retrieval lexical ainda e simples, alguns casos podem esperar `low_confidence` mesmo quando ha documentos relacionados. Isso e uma linha de base do MVP, nao o comportamento final desejado.

Quando provider real, pgvector ou LangChain entrarem, estes casos devem evoluir para validar conteudo mais forte.

## Suite pgvector/provider real

A suite `evals/pgvector_real.yaml` deve ser criada somente depois do relatorio
anonimo da HostGator chegar. Ate la, use
`evals/pgvector_real.example.yaml` apenas como template.

Objetivo dessa suite:

- validar perguntas anonimas parecidas com o suporte real
- medir se o pgvector recupera as referencias esperadas
- medir se `confidence` e `handoff_reasons` estao coerentes
- garantir que `error_code` fique ausente em casos saudaveis
- calibrar antes de promover `RETRIEVAL_BACKEND=pgvector` como padrao

Ela deve ser rodada de forma opt-in em ambiente privado com:

- `DATABASE_URL` configurado
- provider real configurado, como `OPENAI_API_KEY`
- conhecimento do dominio ingerido no pgvector

O processo de entrada dos casos esta em
`docs/runbooks/hostgator-anonymous-eval-intake.md`.

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
