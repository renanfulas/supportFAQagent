# Estado Da Documentacao

## Fontes Ativas De Verdade

Use estes documentos para tomar decisoes atuais:

- `README.md`: status publico resumido;
- `docs/project-map.md`: estado de cada frente (feito, em andamento, falta) e
  mapa das pastas de documentacao;
- `docs/MVP/mvp-plan.md`: escopo e fase atual;
- `docs/MVP/technical-implementation-plan.md`: estado tecnico e ownership;
- `docs/quality-plans/phase0-operational-risk-reduction.md`: gates da Fase 0;
- `docs/runbooks/phase0-staging-promotion-evidence.md`: evidencia obrigatoria
  para promocao;
- `docs/setup/environments.md`: fronteiras entre local, staging e producao;
- `docs/architecture/integration-contracts.md`: contratos HTTP e de integracao;
- `docs/navigation.md`: mapa atual do repositorio.
- `docs/archive/README.md`: indice de planos concluidos e documentos
  historicos, com seus substitutos ativos.

## Estado Consolidado

- Fases 1-4 do nucleo tecnico: concluidas para o MVP;
- Fase 0: implementada, integrada pelo PR `#64` e validada localmente com
  PostgreSQL/pgvector real e `356 passed`;
- Fase 0 operacional: `not_approved` ate executar restore cronometrado em
  ambiente isolado e medir `RPO <= 24h` / `RTO <= 4h`;
- Fase 5: em andamento, concentrada em operacao, capacidade, observabilidade e
  acompanhamento do pgvector como default de staging. `n8n` foi removido do
  projeto (assets `deploy/n8n/`, aliases de config e runbooks dedicados) e nao
  faz parte do plano operacional.

## Proxima Ordem Tecnica

1. Executar restore cronometrado em ambiente isolado a partir do snapshot.
2. Validar PostgreSQL, API, migrations, readiness, pgvector, outbox e volumes
   do agente no ambiente restaurado.
3. Medir `RPO <= 24h` e `RTO <= 4h`.
4. Gerar o relatorio operacional final e decidir promocao da Fase 0.

Os quatro hardenings locais anteriormente bloqueantes foram concluidos e
validados em 15/06/2026. Consulte
`docs/runbooks/local-phase0-hardening-report-2026-06-15.md`.

Em 18/06/2026, o acesso SSH ao staging voltou, o disco foi reduzido de `100%`
para `81%`, o checkout remoto foi promovido para `61ea039`, as migrations
`001-008` foram verificadas, readiness passou, os testes PostgreSQL opt-in
passaram em banco descartavel e a `pgvector_gate.yaml` fechou em `76/78`.
Em 19/06/2026, `RETRIEVAL_BACKEND=pgvector` foi confirmado como default
operacional do staging, com readiness de retrieval `pgvector` ok e rollback
documentado para `RETRIEVAL_BACKEND=lexical`. A promocao operacional continua
`not_approved` somente porque o restore cronometrado em ambiente isolado ainda
nao foi executado. Consulte
`docs/runbooks/phase0-staging-promotion-evidence.md`.

Em 01/07/2026, a migration `013_customer_contact_and_consent.sql` foi aplicada
no staging e `ENABLE_HANDOFF_CONSENT_GATE=true` entrou em operacao, com smoke
real ponta a ponta (Postgres + OTP via WhatsApp) e `run_domain_eval
suporte-vps-whatsapp` com chave real + pgvector sem falhas. Evidencias em
`docs/quality-plans/customer-identity-whatsapp-handoff-plan.md` (Sprint 4b).

Em 02/07/2026, tres frentes fecharam do lado de codigo:

- **Hardening do funil de vendas**: `confidence_threshold` do dominio `vendas`
  baixado de `0.55` para `0.45` (decisao 2, com base no dado do WS-0). Evals e
  suites de confinamento verdes; muda comportamento em prod so no proximo
  deploy/restart. Ver `docs/quality-plans/vendas-funnel-hardening-plan.md`.
- **Enriquecimento de push do support inbox (Sprint 5)**: a notificacao adiada
  pelo gate de consentimento LGPD agora carrega o contato autorizado (nome,
  e-mail, final do WhatsApp verificado); o detalhe do inbox expoe o mesmo bloco
  `customer` via join com `customers`; `POST /web/handoff/consent` devolve
  `customer_name`. Ver `docs/quality-plans/customer-identity-whatsapp-handoff-plan.md`
  (Sprint 5) e `docs/architecture/integration-contracts.md`.
- **Eval do recall (tiering Fase 4)**: suite opt-in
  `domains/suporte-vps-whatsapp/evals/summary_recall.yaml` valida que o resumo
  recuperado melhora e nao polui a resposta. O primeiro run com LLM real
  revelou que o rotulo antigo do bloco de resumo no prompt fazia o modelo
  recusar usar o recall; corrigido em `app/orchestration/prompt_builder.py`.
  Confirmado tambem na VPS (deploy ate `c57248e`) contra pgvector + LLM reais,
  3/3. Ver `docs/quality-plans/conversation-persistence-tiering-tech-plan.md`
  (Fase 4).

## Documentos Historicos

Planos antigos podem citar Alexandre e Silotto ou descrever entregas que ja
foram incorporadas. Eles devem ser lidos como registro historico quando o
proprio documento declarar essa natureza.

Nao apague documentos historicos somente por conterem ownership antigo. Corrija
ou mova para `docs/archive/` quando houver risco de um operador seguir
instrucoes obsoletas.

## Regra De Atualizacao

Uma mudanca que altera status, ownership, contrato HTTP, migration ou operacao
deve atualizar primeiro as fontes ativas acima. Runbooks executaveis nunca
podem depender apenas de contexto historico.
