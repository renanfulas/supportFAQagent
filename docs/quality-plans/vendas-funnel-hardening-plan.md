# Plano Tecnico - Hardening do Funil de Vendas no WhatsApp

Status: planejamento tecnico ativo; nenhuma mudanca implementada ainda.
Data de revisao: 2026-06-26.
Owner de coordenacao: Renan. Frentes envolvidas: Renan (handoff/orquestracao/seguranca),
Alexandre (fila de handoff/persistencia), Silotto (deploy), Juliano (retrieval).

Fontes relacionadas: `docs/domain-contract.md`, `docs/domain-evals.md`,
`docs/integration-contracts.md`, `docs/observability.md`,
`docs/quality-plans/whatsapp-sticky-domain-routing-plan.md`,
`docs/quality-plans/customer-identity-whatsapp-handoff-plan.md`,
memoria de sessao `whatsapp-vendas-smoke-findings`.

## 1. Origem e evidencia

Smoke de 10 conversas no cerebro real do WhatsApp na VPS (2026-06-26), dirigindo
`HermesChatTransport -> DomainRouter + ChatFlowService` com pgvector e LLM real
(`gpt-4o-mini`), bridge stubado (sem envio) e **persistencia desligada** (sem
escrita em prod).

Forcas confirmadas: roteamento para `vendas` + stickiness; precos VPS grounded do
pgvector (sem alucinacao); guardrail de desconto inventado segura; migracao
gratuita correta.

Fraquezas observadas e ja reconciliadas com o codigo:

- **`confidence` e baseada em retrieval**, nao em auto-report do LLM
  (`app/orchestration/confidence.py` usa so os scores dos chunks; ignora a
  pergunta). Calibrar threshold em cima disso e calibrar um manometro cego.
- **Em prod (postgres) todo turno `escalated=true` enfileira `handoff.requested`**
  (`app/db/operational.py`, branch de handoff). Logo a sobre-escalacao por
  `low_confidence` inunda a fila humana de verdade.
- **O loop de descoberta foi amplificado pelo smoke com persistencia off**: sem
  historico, o LLM nao lembrava respostas anteriores. Em prod o historico e
  injetado no prompt (`ChatFlowService._build_history`). Portanto #4 e mais
  *enhancement* do que bug, e comeca por verificacao, nao por codigo.

> A base de evidencia e um unico smoke, com persistencia off e inputs proprios.
> Tratar como sinal, nao como medida. A instrumentacao (WS-0) existe para
> substituir essa anedota por dado real antes de qualquer calibracao.

## 2. Principios e restricoes (nao-negociaveis)

1. **Nao quebrar o gate deterministico.** `domains/vendas/evals/cases.yaml` espera
   `should_escalate: true` + `low_confidence` na trilha lexical/MVP. Mudancas
   mantem `low_confidence` como *reason* (em single-turn sem historico o
   comportamento nao muda) e alteram apenas **o que fazemos** com o sinal.
2. **Core reutilizavel.** Detector de PAN e taxonomia de reasons vivem em
   `app/core/` e `app/handoff/`, servindo web + Meta + Hermes.
3. **Respeitar fronteiras de dono.** Cerebro/handoff/contratos = Renan; fila e
   persistencia duravel = Alexandre (contrato/seam, nao reescrita); deploy =
   Silotto; expansao de query no retrieval = Juliano (seam opcional).
4. **Toda mudanca comportamental em canal vivo entra atras de flag** (env ou por
   dominio) com rollback sem redeploy.
5. **Evals do runner sao single-turn.** Comportamento multi-turno e coberto por
   unit test, nao pelo runner.

## 3. Ordem de execucao por risco

A ordem nao e por numero do achado; e por risco e dependencia. Seguranca e
instrumentacao primeiro; mudancas que mexem na rede de seguranca por ultimo e
atras de flag.

### WS-1 (primeiro) - Dado de cartao: deteccao, recusa e **redacao antes de persistir**

Por que primeiro: maior valor de seguranca/compliance, menor dependencia externa,
inteiramente na frente do Renan.

Causa-raiz:
- `ChatFlowService._maybe_checkout_answer` so recusa por `decline_phrases`
  textuais; um PAN real ("4111 1111 1111 1111") com "cartao" passa e gera link.
- **Furo de persistencia (corrigido apos teste do plano):** existe redacao na
  borda - `record_chat` ja passa `question`/`answer` por `sanitize_for_persistence`
  (`app/core/persistence_sanitize.py`, via `_sanitize_required` em
  `app/db/operational.py:90`) - mas **PAN nao e um padrao coberto** hoje. Logo o
  cartao e gravado em claro. O fix e adicionar a regra, nao criar uma camada nova.

Mudanca:
- **Estender `app/core/persistence_sanitize.py`** com regra de PAN (regex de
  digitos + validacao de Luhn + **lista de exclusao**: linha digitavel de boleto
  47-48 digitos, CPF/CNPJ, possiveis IDs de pedido). Isso cobre persistencia e log
  de uma vez, sem tocar `operational.py`, e respeita a regra de "nao criar lista
  paralela". Expor `contains_card_number(text)` no mesmo modulo (ou em helper
  vizinho) para reuso no checkout/handoff.
- `_maybe_checkout_answer`: se `contains_card_number` -> `return None` (cede a
  rota de seguranca); nunca gera link.
- `HandoffService.inspect_question`: PAN -> reason novo `card_data`
  (classe HARD_BLOCK + HUMAN_QUEUE; ver WS-3).
- `_build_hardened_response`: mensagem dedicada de coaching + escala, sem ecoar o
  dado ("nao envie dados de cartao por aqui; o pagamento e concluido em ambiente
  seguro com um especialista").

Seam de teste/eval:
- `tests/test_pii_card.py` (Luhn aceita PAN valido; rejeita 16 digitos aleatorios,
  CEP, telefone, boleto, CPF/CNPJ).
- `tests/test_vendas_checkout.py` (PAN presente -> nao gera link, retorna recusa).
- Teste anti-eco: PAN nunca aparece em answer nem em registro persistido.
- Nova suite `domains/vendas/evals/confinement/payment_data.yaml`.
- Rodar `security-review` no detector (atencao a ReDoS no regex).

Flag: `VENDAS_CARD_DATA_GUARD` (default on apos validar falso-positivo).
Dono: Renan. Risco: baixo-medio (falso-positivo Luhn/boleto -> teste forte).

### WS-0 (antes de calibrar) - Instrumentacao de funil e escalonamento

Por que antes de WS-2/WS-3: sem medir a distribuicao real de `confidence` e a taxa
por reason em prod, qualquer threshold sai de 10 conversas (overfit).

Mudanca:
- Contadores/metricas (via logging estruturado ja existente, ver
  `docs/observability.md`): taxa de escalacao por reason, taxa de `out_of_scope`,
  fire do checkout, hits de `card_data`, distribuicao de `confidence` por dominio.
- **Harness de smoke fiel e repetivel**: persistencia em schema/scratch isolado
  (nao a tabela de prod), cobrindo multi-turno. Evolui o script ad-hoc
  `scripts/whatsapp_smoke_drive.py` (hoje nao commitado) para algo versionado e
  seguro, sem enfileirar handoff real.

Seam de teste: o proprio harness vira a evidencia de aceitacao das demais WS.
Dono: Renan (metricas) + alinhamento com Silotto (onde rodar) e Alexandre (schema
scratch). Risco: baixo.

### WS-2 - `out_of_scope` ciente de contexto (atras de flag)

Causa-raiz: `HandoffService._has_domain_signal` so olha keywords da mensagem
atual; follow-up de descoberta ("100 visitas por dia") sem keyword vira
`out_of_scope` (BLOCKING) e descarta a resposta do LLM.

Mudanca:
- `HandoffService.decide(...)` recebe `recent_user_texts` (ou flag
  `conversation_has_domain_signal`). `_has_domain_signal` passa a considerar a
  mensagem atual + turnos recentes do usuario.
- `ChatFlowService.answer` ja monta `history`; passa os textos para `decide`.
- **Janela/decaimento explicitos** (ex.: ultimos N turnos), para uma keyword
  antiga nao manter o escopo aberto para sempre.

Risco proprio (autogol): tornar o sinal "pegajoso" pode **mascarar out_of_scope
legitimo** (ex.: lead em vendas que pede config de nginx). Mitigacoes:
- janela curta + so keywords fortes (>= 4 chars, nao genericas);
- manter os reasons fortes (secret/prompt-injection/sensitive) intactos;
- caso de teste multi-turno cobrindo *suprime falso positivo* **e** *nao mascara
  out_of_scope real*.

Seam de teste: `tests/test_handoff_service.py` (multi-turno; suites de
confinamento single-turn permanecem verdes mas nao cobrem isto -> unit test e a
rede).
Flag: `VENDAS_CONTEXT_AWARE_SCOPE`. Dono: Renan. Risco: medio.

### WS-3 - Separar sinal soft de fila humana (contrato com Alexandre)

Causa-raiz: `escalated = bool(reasons)` mistura tres conceitos; `low_confidence`
hoje enfileira handoff humano em prod a cada turno.

Mudanca: taxonomia de reasons em `app/handoff/` / `app/orchestration/chat_flow.py`:

| Classe | Reasons | Efeito |
| --- | --- | --- |
| HARD_BLOCK | out_of_scope, secret_request, prompt_injection_attempt, explicit_human_request, card_data | substitui resposta por texto endurecido |
| HUMAN_QUEUE | explicit_human_request, sensitive_topic, secret_request, card_data, billing/contract/payment, provider_error | enfileira `handoff.requested` |
| SOFT_SIGNAL | low_confidence | metrica/log; **nao enfileira, nao substitui** |

- `app/db/operational.py`: hoje um turno escalado grava **dois** efeitos -
  evento `handoff.requested` na `operational_outbox` (~linha 206) **e** uma linha
  em `support_cases` (~linha 278). A regra "so HUMAN_QUEUE enfileira" precisa valer
  para os dois. **Coordenar com Alexandre** (semantica da fila, do caso de suporte
  e consumidor) antes de mexer.
- Decisao em aberto: manter `low_confidence` enfileirando porem **silencioso para
  o usuario** (com throttle/amostragem) em vez de cortar de vez a rede de
  seguranca. Ver secao 4.

Risco de contrato: `escalated` e usado por log `chat_completed`, campo da
`ChatResponse` e consumidor de fila/automacao externa. Decouplar `escalated` de "precisa humano"
e **mudanca de contrato** -> atualizar `docs/integration-contracts.md` e comunicar.

Seam de teste: `tests/test_chat_flow_errors.py` + teste de `operational` com
runtime fake provando que `low_confidence` sozinho nao enfileira.
Flag: `VENDAS_SOFT_LOW_CONFIDENCE`. Dono: Renan + Alexandre. Risco: medio-alto
(contrato + rede de seguranca de bot que cota preco).

### WS-4 - Loop de descoberta e recomendacao de plano nomeado

Comeca por **verificacao**, nao por codigo (o loop pode nao existir em prod).

Camadas (barata -> cara):
1. Verificar com o harness de WS-0 (persistencia em scratch isolado) se o loop
   persiste com historico real.
2. Se persistir: `app/orchestration/prompt_builder.py` instrui usar o historico,
   nao repetir perguntas ja respondidas e avancar para recomendacao nomeada +
   fechamento quando tiver objetivo + trafego + nivel tecnico.
3. Estado estruturado de descoberta (slots) - **so se 1 justificar**. Interim em
   `session_state_store` (in-memory, efemero, WhatsApp-local); versao duravel =
   tabela nova -> contrato com Alexandre.

Risco: a camada 2 empurra o LLM a "fechar/recomendar" e pode aumentar
alucinacao; manter as guardas de honestidade do dominio. O `session_state_store`
in-memory se perde em restart e quebra com >1 worker.
Dono: Renan (prompt/seam) + Alexandre (durabilidade). Risco: baixo (camada 2),
medio (camada 3).

## 4. Riscos conhecidos e o que pode quebrar (red-team)

- **WS-2 + WS-3 juntos reduzem a rede de seguranca** de um bot que cota preco:
  mais resposta automatica + menos escalonamento, justo nos casos de retrieval
  fraco (os mais propensos a erro). Tratar como conjunto, nao isolado; preferir
  "silencioso para o usuario mas ainda sinalizado" a "nao escalar".
- **`compute_confidence` ignora a pergunta** -> chunk forte porem irrelevante da
  confianca alta (sub-escala). Calibrar threshold nao conserta a metrica; um fix
  de fundo (considerar a pergunta/relevancia) e seam do Juliano.
- **Gate deterministico e lexical; canal real e pgvector+OpenAI.** Verde no CI diz
  pouco sobre prod, e este plano amplia a fracao de comportamento so observavel em
  multi-turno + provider real. Por isso WS-0 e o harness fiel sao pre-requisito.
- **Colisao de keywords no roteador** (vendas x suporte: vps/site/email/ssl) e
  causa a montante de parte da baixa confianca. Tratamos sintoma no handoff; a
  raiz pode ser roteamento/separacao de conhecimento (ver roadmap de dominios).
- **Estado em memoria nao escala**: `_shared_rate_limiter` (global de modulo) e
  `InMemorySessionDomainStore` (por processo) ja sao frageis; restart do systemd
  perde sticky/escape/slots e um 2o worker uvicorn quebra dedup/stickiness. WS-4
  camada 3 se apoia nisso -> preferir durabilidade real se for adiante.
- **Deploy/drift:** prod esta em commit antigo com drift nao-commitado de outras
  frentes e sem pipeline limpo. PR na `main` nao chega vivo em prod sozinho;
  deploy e sync manual cirurgico (Silotto). Sem isso, fix fica na prateleira ou um
  deploy atropela drift alheio.
- **PAN:** Luhn tem falso-positivo (~10% de 16 digitos aleatorios, e blocos de
  boleto) e falso-negativo trivial (cartao por extenso/quebrado). E mitigacao
  parcial; nao criar falsa sensacao de "tratamos cartao 100%".
- **Custo/latencia:** menos out_of_scope + menos escala = mais chamadas pagas ao
  OpenAI. Acompanhar via `docs/cost-latency-profile.md`; rate limiter e a unica
  trava hoje.

## 5. Pre-requisitos transversais

- Mecanismo de **feature flag por dominio** para WS-1..WS-4.
- **Schema/scratch isolado** para o harness de smoke (evitar escrever na auditoria
  de prod e enfileirar handoff real) - alinhar com Alexandre.
- **Janela de deploy + rollback** com Silotto, ciente do drift atual.
- Atualizar `docs/integration-contracts.md` quando `escalated` mudar de semantica.

## 6. Validacao (por PR)

```bash
python -m pytest
python -m compileall app tests scripts
python -m app.evals.run_domain_eval vendas
python -m app.evals.run_domain_eval vendas --file evals/confinement/secrets.yaml
python -m app.evals.run_domain_eval suporte-vps-whatsapp   # regressao do vizinho de roteador
```

Via deterministica (memoria `deterministic-domain-eval-run`):
`OPENAI_API_KEY="" ANTHROPIC_API_KEY="" RETRIEVAL_BACKEND="lexical" PERSISTENCE_BACKEND="disabled"`.
Aceitacao final: re-rodar o smoke de 10 conversas pelo harness de WS-0.

## 7. Sequencia de PRs

1. PR-WS1a: `app/core/pii.py` + testes (detector isolado, sem efeito de produto).
2. PR-WS1b: redacao de PAN na persistencia/log + recusa no checkout + reason
   `card_data` + suite de confinamento.
3. PR-WS0: instrumentacao de metricas + harness de smoke versionado.
4. PR-WS2: `out_of_scope` ciente de contexto, atras de flag.
5. PR-WS3: taxonomia de reasons + fila so para HUMAN_QUEUE (com Alexandre).
6. PR-WS4: verificacao + prompt; camada de slots so se justificada.

## 8. Resultado do teste do plano (2026-06-26)

Passada de verificacao das premissas contra o codigo atual.

Corrigido no plano:
- **WS-1 reusa `app/core/persistence_sanitize.py`** em vez de criar `app/core/pii.py`
  para redacao. A redacao na borda ja existe e ja se aplica a `question`/`answer`;
  o que falta e a regra de PAN. Severidade do "PAN em repouso" e real porem o fix
  e pequeno e localizado (menor risco que o estimado).
- **WS-3 atinge dois sumidouros**, nao um: `operational_outbox` (`handoff.requested`)
  e `support_cases`. A regra HUMAN_QUEUE precisa cobrir ambos.

Confirmado:
- Eval runner e single-turn (sem suporte a historico) - WS-2/WS-4 dependem de unit
  test (`tests/test_conversation_history.py`, `tests/test_prompt_builder.py` servem
  de molde).
- `record_chat` realmente enfileira handoff (premissa WS-3 valida).

Ainda em aberto / merece atencao (nao resolvido pelo plano):
- **Mecanismo de flag por dominio nao existe** como primitiva; ha so flags `enable_*`
  globais e a lista `whatsapp_router_domains`. Decidir o mecanismo (campo em
  `domain.yaml` vs lista por env) antes de WS-2/WS-3. Ver decisao 5.
- **Sem ambiente de staging limpo** para o harness de WS-0 (memoria
  `vps-runtime-topology`): o schema/scratch isolado precisa ser criado, e isso
  depende do Alexandre. E o caminho critico que destrava a medicao de WS-2/WS-3/WS-4.
- **`compute_confidence` ignorar a pergunta** continua sendo divida de fundo nao
  endereçada por nenhuma WS (seria seam do Juliano).

## 9. Decisoes abertas (precisam de dono antes de codar)

1. **Fila (WS-3):** parar de enfileirar `low_confidence` ou manter enfileirando
   silencioso/throttled? (Alexandre + Renan)
2. **Threshold (WS-3):** manter 0.55 e resolver so por taxonomia, ou tambem baixar
   `confidence_threshold` do vendas apos dado do WS-0?
3. **WS-4:** comecar so por verificacao + prompt e decidir slots depois?
4. **Deploy:** quem opera o sync para prod e em que janela, dado o drift? (Silotto)
5. **Flags:** padronizar um mecanismo de flag por dominio antes de WS-2/WS-3?
