# Plano tecnico - Qualidade de provider e runtime de LLM

## Objetivo

Estabilizar o uso de provider real no fluxo `/chat`, mantendo fallback seguro,
observabilidade clara e isolamento entre o core da aplicacao e SDKs externos.

Esta frente pode rodar em paralelo ao adapter `pgvector` e a persistencia, porque
atua principalmente em `app/llm`, `app/orchestration`, configuracao e testes.
Ela nao deve mudar schema SQL, workflows n8n ou deploy definitivo da VPS.

## Problema observado

O projeto ja possui `LLMWrapper`, `LLMService`, provider real por dominio e
fallback seguro. Mesmo assim, antes de expor canais reais, a frente precisa
ficar previsivel em falhas de credencial, timeout, erro de provider e resposta
vazia.

Lacunas principais:

- diferenciar claramente provider indisponivel, timeout e resposta vazia
- preservar `request_id` e `error_code` em todas as falhas relevantes
- evitar vazamento de segredo, prompt completo ou PII em logs
- manter mock estavel nos testes sem mascarar problemas do provider real
- definir quando a UI local pode usar `X-LLM-API-Key` com seguranca

## Escopo

Entram nesta frente:

- revisar `app/llm/service.py` e `app/llm/wrapper.py`
- revisar tratamento de erro em `app/orchestration/chat_flow.py`
- consolidar codigos observaveis de erro em `app/core/errors.py`
- validar configuracao em `app/core/config.py`
- cobrir falhas em `tests/test_llm_service.py` e `tests/test_chat_flow_errors.py`
- conferir contrato em `docs/integration-contracts.md` quando mudar payload

Ficam fora desta frente:

- troca do vector store ativo
- schema SQL e persistencia de conversas
- automacao n8n
- mudanca ampla de prompt
- dashboard de observabilidade
- rotacao ou armazenamento real de secrets

## Contrato esperado

Para qualquer chamada ao provider real, o comportamento esperado e:

- sucesso retorna resposta textual, sem quebrar `ChatResponse`
- falta de credencial retorna fallback seguro com `error_code`
- timeout retorna erro rastreavel sem stack trace para o usuario
- resposta vazia nao vira resposta inventada
- erro externo preserva `request_id` e nao vaza segredo
- testes continuam podendo usar provider mock de forma deterministica

## Arquivos alvo

```text
app/llm/base.py
app/llm/service.py
app/llm/wrapper.py
app/core/config.py
app/core/errors.py
app/orchestration/chat_flow.py
tests/test_llm_service.py
tests/test_chat_flow_errors.py
tests/test_request_observability.py
docs/integration-contracts.md
docs/observability.md
```

## Implementacao sugerida

Passos recomendados:

- mapear erros atuais de `LLMWrapper`
- padronizar excecoes internas para provider indisponivel, timeout e resposta invalida
- garantir que `ChatFlowService` sempre transforma falhas em resposta segura
- confirmar que `error_code` segue serializavel no contrato `/chat`
- testar OpenAI/Anthropic por configuracao sem acoplar o restante do app
- registrar somente metadados seguros em logs

## Conteudo proibido

Esta frente nao deve:

- logar API keys, headers sensiveis ou valores de `.env`
- devolver stack trace para usuario final
- salvar prompt completo com PII em log de producao
- acoplar rotas FastAPI diretamente aos SDKs de provider
- tornar provider real obrigatorio para rodar a suite local

## Testes a adicionar ou revisar

Casos minimos:

- provider mock responde sem credencial externa
- provider real sem credencial retorna fallback seguro
- erro do provider produz `error_code`
- resposta vazia do provider nao gera resposta falsa
- `request_id` aparece no header, corpo e log esperado
- `X-LLM-API-Key` so funciona nas condicoes ja documentadas

## Validacao

Durante a frente:

```powershell
python -m pytest tests/test_llm_service.py tests/test_chat_flow_errors.py
python -m pytest tests/test_request_observability.py
```

Validacao completa antes de commit:

```powershell
python -m compileall app scripts tests
python -m pytest
python -m app.evals.run_domain_eval suporte-vps-whatsapp
```

## Criterios de pronto

- Falhas de provider sao previsiveis e rastreaveis.
- `error_code` nao quebra o contrato de `/chat`.
- Nenhum segredo aparece em logs ou respostas.
- Testes cobrem sucesso, credencial ausente, timeout/erro e resposta vazia.
- O provider mock continua simples para desenvolvimento local.
- A documentacao de integracao reflete qualquer mudanca de contrato.

## Estimativa

- Mapear erros e contratos: 30 a 45 minutos
- Ajustar servicos e testes: 1 a 2 horas
- Rodar validacao e calibrar fallback: 30 a 60 minutos

Total esperado: 2 a 3,5 horas.
