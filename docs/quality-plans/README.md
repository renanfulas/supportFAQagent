# Planos de qualidade por frente

Esta pasta concentra planos executaveis de qualidade para frentes do MVP que
ainda seguem abertas ou parcialmente abertas. Cada plano segue o mesmo formato
basico: objetivo, escopo, arquivos alvo, validacao, criterios de pronto e
riscos de fronteira.

Use os planos ainda presentes nesta pasta antes de abrir codigo novo em uma
frente especifica. Para o estado consolidado de todas as frentes (feito, em
andamento, falta), veja [`docs/project-map.md`](../project-map.md). O plano
concluido de retrieval vetorial foi movido para
[`docs/archive/implementation-plans/`](../archive/implementation-plans/vector-retrieval-quality-plan.md).

Planos ativos (com tarefa executavel restante):

- [`customer-identity-whatsapp-handoff-plan.md`](customer-identity-whatsapp-handoff-plan.md):
  integracao entre Auth WhatsApp, identidade do cliente, historico,
  preferencias de front end, ticket humano e notificacao WhatsApp para o time.
  Falta so a extensao "minion" (bloqueada no Juliano).

- [`meta-whatsapp-native-integration-plan.md`](meta-whatsapp-native-integration-plan.md):
  refatoracao de entrega externa para Meta WhatsApp Cloud API nativa, com
  Hermes apenas como adapter temporario.

- [`web-chat-evolution-plan.md`](web-chat-evolution-plan.md): evolucao do chat
  web (V0 publica ja incorporada; fases seguintes de identidade e WhatsApp).

- [`web-chat-v1-whatsapp-otp-spec.md`](web-chat-v1-whatsapp-otp-spec.md):
  contrato, threat model e fronteiras da identidade de canal por WhatsApp OTP.

- [`conversation-persistence-tiering-plan.md`](conversation-persistence-tiering-plan.md) +
  [`...-tech-plan.md`](conversation-persistence-tiering-tech-plan.md): persistencia
  em camadas (Redis, batch, resumo, recall). Falta so a Fase 0 (sink R2,
  bloqueado por credenciais) e a metrica de custo.

- [`phase0-operational-risk-reduction.md`](phase0-operational-risk-reduction.md):
  gates da Fase 0 (persistencia/migrations/outbox). Falta o restore cronometrado
  em ambiente isolado (Juliano).

- [`pgvector-gate-backlog-2026-06-11.md`](pgvector-gate-backlog-2026-06-11.md):
  saneamento offline dos casos da gate pgvector; 2 dos 4 casos originais ainda
  falham (`vps-049-disco-cheio`, `vps-091-banco-consome-disco`, hoje por
  `unexpected_escalation`, nao mais por referencia).

Quando uma parte da frente ja tiver sido implementada e mergeada, o plano deve:

- marcar claramente o que ja foi entregue
- focar apenas no que ainda falta para fechar a frente
- apontar para os testes, evals e docs que ja viraram fonte de verdade

Frentes totalmente encerradas devem sair desta pasta quando o plano virar
historico. Nesses casos, o plano vai para `docs/archive/` e a fonte de verdade
passa a ser:

- o estado atual do codigo
- os docs principais do projeto
- os testes e evals que provaram a entrega
