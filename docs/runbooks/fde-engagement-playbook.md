# Runbook - Playbook De Implantacao (FDE)

## Objetivo

Guiar um Forward Deployed Engineer (FDE) a levar o `supportFAQagent` para um
cliente novo, da descoberta ao go-live, de forma repetivel: mesmo contrato de
dominio, mesmos gates de seguranca, mesmas metricas de valor.

O produto responde com base em conhecimento controlado e escala para humano
quando falta contexto. O FDE **nao promete autonomia total**: o compromisso com
o cliente e reduzir repeticao com rastreabilidade e fallback seguro (ver
[`product-positioning.md`](../product-positioning.md)).

## Modelo de implantacao (estado atual)

- **Uma instancia por cliente.** O core isola dados por `domain_id`, mas nao
  tem conceito de tenant. Cliente novo = ambiente proprio (banco, segredos,
  variaveis), nao dominio novo dentro do ambiente de outro cliente.
- **Dominio como plugin.** O comportamento do cliente entra por
  `domains/<dominio>/`, sem codigo no core
  ([`framework-boundary.md`](../architecture/framework-boundary.md),
  [`domain-contract.md`](../architecture/domain-contract.md)).
- **Conhecimento hoje entra por arquivo** (`knowledge/` em Markdown) ou pelo
  loader do GitHub ([`knowledge-authoring.md`](../architecture/knowledge-authoring.md)).
  Conector para outra fonte do cliente (wiki, help center) e trabalho novo, a
  estimar na descoberta.

## Semana 0 - Descoberta

Saia da descoberta com respostas escritas para:

| Tema | Pergunta | Vira o que |
| --- | --- | --- |
| Volume | Quantos contatos por dia/semana, por canal? | Baseline de valor |
| Motivos | Quais os 20 motivos de contato mais frequentes? | Primeiros artigos e casos de eval |
| Resolucao hoje | Como o time responde cada motivo? Ha script/macro? | Conteudo de `knowledge/` |
| Proibido | O que o agente **nunca** pode responder ou prometer? | `out_of_scope`, `sensitive_terms` |
| Risco | Quais temas exigem humano sempre (cobranca, juridico, incidente)? | `escalation_rules`, `explicit_human_phrases` |
| Canal | Web, WhatsApp, outro? Quem e o dono do numero/site? | Integracao e runbook de smoke |
| Humano | Quem atende o handoff, em que horario, com que SLA? | Fila do console e meta de tempo |
| Sistemas | Onde o ticket do cliente precisa aparecer (helpdesk, CRM)? | Contrato de integracao (outbox) |
| Dados | Ha DPO/responsavel LGPD? Retencao exigida? | Gate de consentimento e retencao |
| Sucesso | Qual numero define sucesso em 30/60/90 dias? | Criterio de aceite do go-live |

Registre o baseline **antes** de ligar o agente: volume, tempo de primeira
resposta e taxa de resolucao atual. Sem baseline nao ha como provar valor.

## Semana 1 - Dominio e conjunto de avaliacao

1. Gere o dominio:

   ```bash
   python -m scripts.new_domain <cliente-area> --display-name "Nome" --owner "Time do cliente"
   ```

   O scaffold cria `domain.yaml` com as politicas de confinamento preenchidas,
   `provider: mock`, pastas de conhecimento vazias e as suites
   `evals/confinement/` (fora do escopo, redefinicao, segredos), com casos
   espelho `-acentuado`. Use `--dry-run` para ver os arquivos antes.

2. Resolva os `TODO(FDE)` do `domain.yaml` com as respostas da descoberta.

3. Escreva os primeiros artigos para os motivos mais frequentes, um problema
   por arquivo ([`knowledge-authoring.md`](../architecture/knowledge-authoring.md)).

4. Monte o conjunto de avaliacao a partir de conversas reais **anonimizadas**
   ([`anonymous-eval-intake.md`](anonymous-eval-intake.md)). Cada caso aponta o
   artigo esperado em `expected_references`.

5. Rode os evals com o provider mock:

   ```bash
   python -m app.evals.run_domain_eval <dominio>
   python -m app.evals.run_domain_eval <dominio> --file evals/confinement/out_of_scope.yaml
   python -m app.evals.run_domain_eval <dominio> --file evals/confinement/redefinition.yaml
   python -m app.evals.run_domain_eval <dominio> --file evals/confinement/secrets.yaml
   ```

Pronto quando: confinamento 100% verde e cada motivo frequente tem artigo e
caso de eval.

## Semana 2 - Provider real em staging

1. Ambiente de staging do cliente, com credenciais so em variavel de ambiente
   ([`environments.md`](../setup/environments.md)). Nunca commitar chave.
2. Troque `llm.provider` para o provider real e rode os mesmos evals. Os
   resultados com mock e com provider real **nao sao comparaveis**: o mock
   valida roteamento e confinamento; qualidade de resposta so com provider real
   ([`staging-pgvector-real-eval.md`](staging-pgvector-real-eval.md)).
3. Calibre `handoff.confidence_threshold` olhando conversas reais, nao no
   escuro (exemplo de calibragem medida em
   [`vendas-funnel-hardening-plan.md`](../quality-plans/vendas-funnel-hardening-plan.md)).
4. Se o canal atende mais de um dominio, valide o roteamento antes de incluir o
   dominio no roteador (`WHATSAPP_ROUTER_DOMAINS`) e cubra a colisao em
   `tests/test_domain_router.py`.
5. Meca custo e latencia por request com `python -m scripts.profile_cost_latency`.

Pronto quando: taxa de acerto dos casos reais acima da meta combinada na
descoberta, e nenhum caso de confinamento falhando.

## Semana 3 - Piloto controlado

- Comece com uma fatia pequena: um canal, um horario ou uma porcentagem do
  trafego, com o time humano avisado e a fila do console atendida
  ([`support-console-smoke.md`](support-console-smoke.md)).
- Rode o smoke do ambiente ([`staging-http-smoke.md`](staging-http-smoke.md)) e
  o gate de prontidao (`python -m scripts.check_readiness`).
- Revise diariamente: handoffs, respostas marcadas como ruins no feedback e
  perguntas sem artigo. Cada lacuna vira artigo + caso de eval, nunca ajuste
  "no prompt" sem eval.

## Checklist de go-live

- [ ] Suites de confinamento 100% verdes com o provider real.
- [ ] Casos reais acima da meta combinada; resultado salvo como evidencia.
- [ ] Fila humana com dono, horario e SLA; handoff testado ponta a ponta.
- [ ] Gate de consentimento ligado onde ha coleta de contato
      (`ENABLE_HANDOFF_CONSENT_GATE`).
- [ ] Backup e restore ensaiados ([`phase0-snapshot-restore.md`](phase0-snapshot-restore.md)).
- [ ] Alerta de capacidade configurado ([`vps-controlled-runtime.md`](vps-controlled-runtime.md)).
- [ ] Plano de rollback escrito: tirar o dominio do roteador, desligar a flag
      do canal ou voltar o provider para mock.
- [ ] Nenhum segredo, PII crua ou `session_id` cru em log
      ([`observability.md`](../architecture/observability.md)).

## Metricas de valor (30/60/90 dias)

| Metrica | De onde vem |
| --- | --- |
| Resolvido sem humano | Turnos nao escalados com feedback nao negativo |
| Taxa de handoff, por motivo | `handoff_reasons` nas respostas e no console |
| Tempo ate o primeiro humano | Metricas do console (`app/support/metrics.py`) |
| Custo e latencia por request | `scripts/profile_cost_latency.py` |
| Lacunas de conhecimento | Perguntas sem referencia e feedback negativo |

Compare sempre com o baseline da Semana 0.

## Passagem para o time do cliente

- Dono do dominio nomeado no `owner` do `domain.yaml`.
- Rotina combinada de revisao de lacunas e de evals (ex.: semanal).
- Regra de mudanca: artigo ou regra nova entra com caso de eval e com os
  evals do dominio rodando verdes.

## Limites conhecidos (seja honesto com o cliente)

- **Sem multi-tenant:** um ambiente por cliente.
- **Conectores de conhecimento:** apenas arquivos e GitHub.
- **Integracao com helpdesk/CRM do cliente:** via outbox + webhook; conector
  dedicado e trabalho novo.
- **`prompts/` nao e lido pelo codigo:** o prompt efetivo e montado a partir
  do `domain.yaml` em `app/orchestration/prompt_builder.py`. Para mudar
  comportamento, edite o `domain.yaml`.
- **Deploy:** o script atual (`scripts/deploy_ask_host_genius.*`) e especifico
  do primeiro cliente; generaliza-lo e trabalho pendente.
- **Console da equipe:** login proprio, sem SSO.
