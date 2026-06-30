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

Planos ativos:

- [`customer-identity-whatsapp-handoff-plan.md`](customer-identity-whatsapp-handoff-plan.md):
  integracao entre Auth WhatsApp, identidade do cliente, historico,
  preferencias de front end, ticket humano e notificacao WhatsApp para o time.

- [`meta-whatsapp-native-integration-plan.md`](meta-whatsapp-native-integration-plan.md):
  refatoracao de entrega externa para Meta WhatsApp Cloud API nativa, com
  Hermes apenas como adapter temporario.

- [`web-chat-evolution-plan.md`](web-chat-evolution-plan.md): evolucao do chat
  web (V0 publica ja incorporada; fases seguintes de identidade e WhatsApp).

- [`web-chat-v1-whatsapp-otp-spec.md`](web-chat-v1-whatsapp-otp-spec.md):
  contrato, threat model e fronteiras da identidade de canal por WhatsApp OTP.

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
