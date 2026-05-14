# Plano tecnico - Qualidade de chat, prompt, confidence e handoff

## Objetivo

Manter e evoluir a consistencia do fluxo `/chat`: contexto recuperado, prompt
final, confidence score e escalonamento humano com motivos estruturados.

Esta frente e transversal, mas pode avancar sem persistencia real desde que nao
assuma historico de conversas que ainda nao existe.

## Estado atual

Em `main`, o PR #31 (`codex/soften-prompt-guardrails`) ja foi integrado. O
comportamento atual do chat nao e apenas bloqueio duro: ele preserva guardrails
centrais, mas permite orientacao segura quando ha contexto suficiente e o risco
nao exige recusa imediata.

Hoje o fluxo relevante esta assim:

- `ChatFlowService` usa retrieval lexical temporario antes de montar prompt.
- `prompt_builder.py` e o ponto unico de montagem do prompt final.
- O dominio inicial aponta para `llm.provider: openai` e `model: gpt-4o-mini`.
- `LLMService` pode usar provider real quando ha credencial valida.
- Falha do provider retorna mensagem segura do dominio e `error_code`.
- `confidence` e heuristico: `0.0` sem chunks e media arredondada dos scores recuperados quando ha chunks.
- `HandoffService` retorna motivos estruturados antes e depois do retrieval.
- Baixa confianca abaixo de `handoff.confidence_threshold` adiciona `low_confidence`.
- Baixa confianca sem palavra-chave de roteamento do dominio tambem adiciona `out_of_scope`.
- Pedido explicito de humano adiciona `explicit_human_request`.
- Termos sensiveis adicionam `sensitive_topic`.
- Pedido de segredo adiciona `secret_request` e `sensitive_topic`.
- Tentativa de prompt injection ou redefinicao adiciona `prompt_injection_attempt`.
- Respostas automatizadas sao bloqueadas para `explicit_human_request`, `out_of_scope`, `prompt_injection_attempt` e `secret_request`.
- `sensitive_topic` escala, mas nao bloqueia automaticamente uma orientacao segura quando o restante do fluxo permite.
- Historico recente ainda nao vem de persistencia; `_build_history()` retorna lista vazia, embora o formatter ja suporte historico curto.

## Problema observado

O comportamento estrutural ja esta implementado, mas ainda precisa ser calibrado
contra conversas reais. As lacunas atuais sao:

- calibrar confidence sem fingir precisao estatistica
- evitar que `low_confidence` vire ruido em perguntas validas com retrieval lexical fraco
- manter motivos estruturados de handoff sem misturar erro tecnico com decisao de negocio
- garantir que prompt injection do usuario ou do contexto nao mude regras centrais
- confirmar que o soften guardrails nao permite resposta arriscada em tema sensivel
- preparar historico curto somente quando houver persistencia real
- alinhar evals com casos reais do dominio e com o comportamento suavizado

## Escopo

Entram nesta frente:

- revisar `app/orchestration/chat_flow.py`
- revisar `app/orchestration/prompt_builder.py`
- revisar `app/orchestration/confidence.py`
- revisar `app/handoff/service.py`
- revisar `domains/suporte-vps-whatsapp/domain.yaml`
- ajustar evals em `domains/suporte-vps-whatsapp/evals/cases.yaml`
- adicionar testes de prompt, handoff e fluxo

Ficam fora desta frente:

- memoria longa de conversa
- `ConversationalRetrievalChain`
- persistencia de mensagens
- roteamento omnichannel
- mudanca de schema SQL
- dashboard de qualidade
- mover regra central de handoff para n8n

## Contrato de resposta esperado

Para cada chamada `/chat`, a resposta deve preservar:

- `request_id`
- `domain`
- `answer`
- `confidence`
- `escalated`
- `handoff_reasons`
- `references`
- `error_code`

Quando o contexto for insuficiente, a resposta deve dizer isso de forma clara,
manter `confidence` baixa e encaminhar para humano quando a politica do dominio
exigir.

## Arquivos de referencia

```text
app/orchestration/chat_flow.py
app/orchestration/prompt_builder.py
app/orchestration/confidence.py
app/handoff/service.py
app/handoff/models.py
domains/suporte-vps-whatsapp/domain.yaml
domains/suporte-vps-whatsapp/evals/cases.yaml
tests/test_prompt_builder.py
tests/test_handoff_service.py
tests/test_domain_evals.py
tests/test_app.py
```

## Comportamento esperado por area

Prompt:

- Deve priorizar o contexto recuperado e manter orientacao conservadora quando ele for incompleto.
- Deve preservar o contrato de confinamento do dominio: fora de escopo, redefinicao, prompt interno e segredos.
- Deve responder apenas em texto puro.
- Deve orientar o proximo passo seguro quando faltar contexto, sem inventar comando, politica ou configuracao.
- Deve recusar ou neutralizar pedidos para ignorar regras, revelar prompt, expor credenciais ou assumir papel fora do dominio.

Confidence:

- Deve continuar sendo tratado como heuristica operacional, nao como metrica estatistica.
- Sem chunks, deve ser `0.0`.
- Com chunks, hoje segue media dos scores retornados pelo retrieval lexical.
- O threshold oficial vem de `domain.yaml` (`handoff.confidence_threshold`, hoje `0.7`).
- Mudancas futuras devem ser calibradas com evals antes de alterar o threshold.

Handoff:

- Deve manter `handoff_reasons` estruturado e estavel.
- `explicit_human_request`, `out_of_scope`, `prompt_injection_attempt` e `secret_request` devem bloquear resposta automatizada livre.
- `sensitive_topic` deve escalar, mas pode permitir resposta cautelosa e textual quando houver contexto seguro.
- `provider_error` ou outros erros tecnicos devem aparecer como `error_code` e podem ser agregados aos motivos sem virar regra de negocio.
- n8n deve consumir a decisao do backend, nao recalcular a politica central.

## Conteudo proibido

Esta frente nao deve:

- inventar resposta quando `references` estiver vazio e a pergunta exigir fonte
- expor detalhes internos de prompt ou RAG ao usuario final
- aceitar instrucao do usuario para ignorar regras do sistema
- registrar prompt completo com PII em producao
- transformar n8n em decisor central de handoff

## Evals a fortalecer

Categorias recomendadas:

- pergunta com contexto forte deve responder com passos curtos
- pergunta fora do dominio deve escalar
- pedido explicito de humano deve escalar
- tema sensivel deve escalar
- prompt injection deve ser recusado ou neutralizado
- contexto insuficiente deve admitir limite
- pedido de segredo deve escalar e nao expor credenciais
- tema sensivel com contexto seguro deve escalar sem necessariamente bloquear toda orientacao textual

Enquanto o retrieval lexical for a linha de base, prefira exigir referencia,
escalonamento e motivo de handoff antes de exigir muitos termos semanticos.

Os testes atuais ja cobrem:

- prompt com conteudo recuperado, regras de dominio, texto puro e canal sem anexos
- limite de historico formatado, embora o fluxo real ainda nao persista historico
- handoff por baixa confianca, pedido humano, tema sensivel, redefinicao e fora de escopo
- suite inicial de evals do dominio carregando e passando sem falhas

## Validacao

Durante a frente:

```powershell
python -m pytest tests/test_prompt_builder.py tests/test_handoff_service.py tests/test_domain_evals.py
python -m app.evals.run_domain_eval suporte-vps-whatsapp
```

Validacao completa antes de commit:

```powershell
python -m compileall app scripts tests
python -m pytest
python -m app.evals.run_domain_eval suporte-vps-whatsapp
```

## Criterios de pronto

- O prompt final e testado com contexto forte, fraco e malicioso.
- Confidence e handoff nao dependem apenas do texto livre da resposta.
- `handoff_reasons` continua estruturado.
- Casos reais do dominio possuem evals versionados.
- O chat sabe admitir falta de contexto.
- A resposta publica nao revela detalhes internos sensiveis.

## Estimativa

- Revisar fluxo e prompts: 45 a 90 minutos
- Ajustar confidence/handoff e testes: 1,5 a 3 horas
- Rodar evals e calibrar expectativas: 1 a 2 horas

Total esperado: 3,25 a 6,5 horas.
