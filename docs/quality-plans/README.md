# Planos de qualidade por frente

Esta pasta concentra planos executaveis de qualidade para frentes do MVP que
ainda seguem abertas ou parcialmente abertas. Cada plano segue o mesmo formato
basico: objetivo, escopo, arquivos alvo, validacao, criterios de pronto e
riscos de fronteira.

Use estes documentos antes de abrir codigo novo em uma frente especifica:

- [Retrieval vetorial](vector-retrieval-quality-plan.md) - fase atual da
  integracao oficial com PostgreSQL + pgvector

Quando uma parte da frente ja tiver sido implementada e mergeada, o plano deve:

- marcar claramente o que ja foi entregue
- focar apenas no que ainda falta para fechar a frente
- apontar para os testes, evals e docs que ja viraram fonte de verdade

Frentes totalmente encerradas devem sair desta pasta quando o plano virar
historico obsoleto. Nesses casos, a fonte de verdade passa a ser:

- o estado atual do codigo
- os docs principais do projeto
- os testes e evals que provaram a entrega
