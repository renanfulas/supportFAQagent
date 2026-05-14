# Plano tecnico - Qualidade de chat, prompt e handoff

## Objetivo

Melhorar a consistencia do fluxo `/chat`: contexto recuperado, prompt final,
confidence score e escalonamento humano com motivos estruturados.

Esta frente e transversal, mas pode avancar sem persistencia real desde que nao
assuma historico de conversas que ainda nao existe.

## Problema observado

O `ChatFlowService` ja usa `prompt_builder.py`, calcula confianca e chama handoff.
Ainda assim, o comportamento precisa continuar previsivel quando o contexto e
fraco, quando o usuario pede humano, quando ha termos sensiveis ou quando o
provider falha.

Lacunas principais:

- calibrar confidence sem fingir precisao estatistica
- garantir que baixa confianca escale
- manter motivos estruturados de handoff
- impedir que prompt injection do usuario ou do contexto mude regras centrais
- preparar historico curto sem depender de persistencia inexistente
- alinhar evals com os casos reais do dominio

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

Quando o contexto for insuficiente, a resposta deve dizer isso de forma clara e
encaminhar para humano quando a politica do dominio exigir.

## Arquivos alvo

```text
app/orchestration/chat_flow.py
app/orchestration/prompt_builder.py
app/orchestration/confidence.py
app/handoff/service.py
app/handoff/models.py
app/api/schemas/chat.py
domains/suporte-vps-whatsapp/domain.yaml
domains/suporte-vps-whatsapp/prompts/system.txt
domains/suporte-vps-whatsapp/prompts/style.txt
domains/suporte-vps-whatsapp/evals/cases.yaml
tests/test_prompt_builder.py
tests/test_handoff_service.py
tests/test_domain_evals.py
tests/test_app.py
```

## Implementacao sugerida

Passos recomendados:

- revisar o prompt final gerado para perguntas com e sem contexto
- garantir que o prompt instrui a responder apenas com contexto recuperado
- separar confidence heuristica de motivos de handoff
- testar pedido explicito de humano em frases reais
- testar termos sensiveis configurados no dominio
- calibrar evals antes de aumentar exigencia semantica

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

Enquanto o retrieval lexical for a linha de base, prefira exigir referencia,
escalonamento e motivo de handoff antes de exigir muitos termos semanticos.

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
