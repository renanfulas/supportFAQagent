# Runbook - Intake de perguntas anonimas HostGator para evals

## Objetivo

Preparar a entrada do relatorio anonimo da HostGator como material de
calibragem de RAG, sem transformar dados brutos em prompt, treinamento de
modelo ou base oficial sem curadoria.

Este fluxo cria uma suite opt-in de evals para validar `pgvector` e provider
real com perguntas parecidas com o suporte real.

## Entradas esperadas

Cada linha do relatorio deve ter, quando possivel:

- pergunta anonima do usuario
- categoria operacional sugerida
- resolucao ou classificacao humana
- artigo/fonte esperada, se conhecida
- indicacao se deve escalar para humano

## Checklist de recebimento

Antes de transformar o relatorio em evals versionados, confirme:

- o arquivo recebido nao contem credenciais, tokens, senhas, chaves ou headers
- telefones, emails, nomes, dominios de cliente, IPs publicos e IDs de conta
  foram removidos ou generalizados
- cada pergunta esta curta o bastante para representar uma unica intencao
- cada pergunta tem uma categoria operacional sugerida
- cada pergunta tem uma decisao humana esperada: responder ou escalar
- cada pergunta tem, quando possivel, uma fonte/artigo esperado
- casos sem fonte esperada foram marcados para curadoria de conhecimento antes
  de virar gate de qualidade
- o arquivo bruto permanece fora do Git

Se algum item acima falhar, trate o relatorio como insumo privado de curadoria,
nao como material pronto para versionamento.

## Regras de privacidade

Antes de versionar qualquer caso:

- remover telefones, emails, nomes, dominios de cliente, IPs publicos e IDs de
  conta
- remover senhas, tokens, chaves, URLs privadas, headers e payloads sensiveis
- trocar identificadores por termos genericos, como `minha VPS`, `meu webhook`
  ou `minha instancia`
- nao incluir conversas longas; transformar em uma pergunta curta e realista
- nao copiar logs crus
- nao versionar pergunta/resposta completa se ainda houver identificador
  reversivel
- nao registrar no relatorio final prompts, headers, payloads, stack traces ou
  valores de ambiente

Se houver duvida se um dado e reversivel, nao versionar.

## Como transformar em eval

1. Copie `domains/suporte-vps-whatsapp/evals/pgvector_real.example.yaml` para
   `domains/suporte-vps-whatsapp/evals/pgvector_real.yaml`.
2. Substitua o caso de exemplo por perguntas anonimas reais.
3. Use categorias curtas, como `setup_tecnico`, `operacao_whatsapp`,
   `integracoes`, `seguranca_escalonamento` ou `orientacao_iniciantes`.
4. Preencha `expected_references` com o artigo que o pgvector deveria recuperar.
5. Marque `should_escalate` conforme a decisao humana esperada.
6. Use `required_terms` apenas para termos essenciais e seguros.
7. Use `allowed_handoff_reasons` para limitar os motivos aceitaveis.

## Como rodar

Esta suite deve ser opt-in e rodada em ambiente preparado:

```powershell
$env:RETRIEVAL_BACKEND = "pgvector"
python -m app.evals.run_domain_eval suporte-vps-whatsapp --file evals/pgvector_real.yaml
```

O ambiente precisa ter:

- `DATABASE_URL` privado apontando para o banco com dados ingeridos
- `OPENAI_API_KEY` ou provider equivalente configurado
- conhecimento do dominio ingerido no pgvector

## Como interpretar

Classifique cada falha antes de alterar codigo:

- `conteudo`: falta ou fraqueza de artigo
- `retrieval`: artigo correto existe, mas nao foi recuperado
- `confidence`: resposta boa, mas escalou por confianca baixa
- `handoff`: escalou ou deixou de escalar contra a expectativa
- `provider`: erro externo ou resposta vazia
- `contrato`: formato publico quebrou

## Criterio para promover pgvector

So considerar `pgvector` como padrao permanente quando:

- perguntas reais anonimas recuperam referencias coerentes
- `error_code` permanece `null` nos casos saudaveis
- escalonamentos por `low_confidence` foram revisados
- casos sensiveis continuam escalando
- nenhum caso versionado contem PII ou segredo
