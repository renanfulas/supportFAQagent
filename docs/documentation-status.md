# Estado Da Documentacao

## Fontes Ativas De Verdade

Use estes documentos para tomar decisoes atuais:

- `README.md`: status publico resumido;
- `docs/mvp-plan.md`: escopo e fase atual;
- `docs/technical-implementation-plan.md`: estado tecnico e ownership;
- `docs/quality-plans/phase0-operational-risk-reduction.md`: gates da Fase 0;
- `docs/runbooks/phase0-staging-promotion-evidence.md`: evidencia obrigatoria
  para promocao;
- `docs/environments.md`: fronteiras entre local, staging e producao;
- `docs/integration-contracts.md`: contratos HTTP e de integracao;
- `docs/navigation.md`: mapa atual do repositorio.
- `docs/archive/README.md`: indice de planos concluidos e documentos
  historicos, com seus substitutos ativos.

## Estado Consolidado

- Fases 1-4 do nucleo tecnico: concluidas para o MVP;
- Fase 0: implementada, integrada pelo PR `#64` e validada localmente com
  PostgreSQL/pgvector real e `356 passed`;
- Fase 0 operacional: `not_approved` ate provar snapshot, restore, rede
  privada, alertas e integracoes em staging;
- Fase 5: em andamento, concentrada em operacao, n8n, Evolution e promocao
  controlada.

## Proxima Ordem Tecnica

1. Restaurar acesso ao staging oficial.
2. Criar snapshot no provedor e executar o preflight de staging.
3. Aplicar o rollout expand/backfill/contract e verificar migrations
   `001-008`.
4. Validar rede privada, n8n, Evolution, outbox e idempotencia externa.
5. Reiniciar o stack e comprovar persistencia.
6. Executar restore cronometrado e medir RPO/RTO.
7. Executar a gate pgvector e decidir promocao operacional.

Os quatro hardenings locais anteriormente bloqueantes foram concluidos e
validados em 15/06/2026. Consulte
`docs/runbooks/local-phase0-hardening-report-2026-06-15.md`.

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
