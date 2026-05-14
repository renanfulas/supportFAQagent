# Plano tecnico - Qualidade de feedback e integracao n8n

## Objetivo

Preparar o contrato de feedback, escalonamento e automacao externa para que n8n
consuma o backend sem mover inteligencia para fora do core Python.

Esta frente pode avancar por contrato e testes antes da persistencia real. A
gravacao definitiva em PostgreSQL continua dependente da frente de banco.

## Problema observado

O endpoint `POST /feedback` ja aceita payload e retorna `pending_persistence`.
O `/chat` ja devolve `request_id`, `escalated`, `handoff_reasons` e `references`.
Falta transformar isso em um guia operacional claro para n8n e futura
persistencia.

Lacunas principais:

- definir payload minimo para escalonamento humano
- preservar `request_id` entre `/chat` e `/feedback`
- evitar que n8n replique regra de negocio do agente
- documentar retries, 403, 429 e falhas de provider
- preparar persistencia sem acoplar rota ao schema final

## Escopo

Entram nesta frente:

- revisar `app/api/routes/feedback.py`
- revisar `app/api/schemas/feedback.py`
- revisar `app/feedback/service.py`
- revisar contrato de `/chat` para n8n
- atualizar `docs/integration-contracts.md`
- atualizar `docs/observability.md`
- adicionar testes de contrato e seguranca

Ficam fora desta frente:

- criar workflow n8n completo
- persistir feedback em PostgreSQL antes do schema estar pronto
- mandar mensagens reais de WhatsApp
- implementar painel de atendimento humano
- mover handoff para n8n
- salvar PII sem politica de retencao

## Contrato operacional esperado

O consumidor externo deve:

- enviar `X-API-Key` nas rotas protegidas
- enviar ou preservar `X-Request-ID`
- guardar `request_id` retornado pelo `/chat`
- rotear para humano quando `escalated=true`
- usar `handoff_reasons` em vez de inferir pelo texto
- enviar `/feedback` com o `request_id` da resposta avaliada

## Arquivos alvo

```text
app/api/routes/chat.py
app/api/routes/feedback.py
app/api/schemas/chat.py
app/api/schemas/feedback.py
app/feedback/service.py
app/core/rate_limit.py
tests/test_feedback.py
tests/test_integration_contracts.py
tests/test_auth.py
tests/test_rate_limit.py
docs/integration-contracts.md
docs/observability.md
```

## Implementacao sugerida

Passos recomendados:

- revisar se o schema de feedback tem campos suficientes para n8n
- documentar quando usar `request_id`, `message_id` e `session_id`
- manter `session_id` tratado como dado sensivel
- definir exemplos de payload para feedback positivo, negativo e escalado
- registrar `feedback_recorded` sem vazar comentario sensivel em log
- preparar status futuro de persistencia sem quebrar `pending_persistence`

## Conteudo proibido

Esta frente nao deve:

- colocar API key em workflow versionado
- logar telefone ou `session_id` bruto
- duplicar regras de prompt, confidence ou handoff no n8n
- considerar `answer` como fonte de verdade para roteamento se `handoff_reasons` existe
- quebrar o contrato atual de `/feedback` sem migracao documentada

## Testes a adicionar ou revisar

Casos minimos:

- `/feedback` exige `X-API-Key`
- payload valido retorna `accepted=true`
- campos opcionais em branco viram `null` quando esperado
- `source` tem default seguro
- comentario grande e rejeitado
- logs usam hash de `session_id`
- contrato documentado bate com schemas reais

## Validacao

Durante a frente:

```powershell
python -m pytest tests/test_feedback.py tests/test_integration_contracts.py
python -m pytest tests/test_auth.py tests/test_rate_limit.py
```

Validacao completa antes de commit:

```powershell
python -m compileall app scripts tests
python -m pytest
```

## Criterios de pronto

- n8n consegue consumir `/chat` e `/feedback` so pelo contrato documentado.
- `request_id` e `handoff_reasons` estao preservados.
- Feedback ainda funciona sem persistencia real.
- Nenhuma regra central de inteligencia foi movida para automacao externa.
- Dados sensiveis sao mascarados ou tratados como sensiveis.
- Testes cobrem autorizacao, validacao e shape de resposta.

## Estimativa

- Revisar contratos atuais: 30 a 60 minutos
- Ajustar schemas/testes/documentacao: 1,5 a 3 horas
- Validar fluxo manual com payloads exemplo: 30 a 60 minutos

Total esperado: 2,5 a 5 horas.
