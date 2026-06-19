# Posicionamento Do Produto

## Proposta

O `supportFAQagent` e um agente de suporte com RAG para responder duvidas recorrentes de VPS, WhatsApp e automacoes com seguranca, rastreabilidade e escalonamento humano.

Ele nao tenta substituir suporte especializado. O produto reduz repeticao, aumenta consistencia e ajuda o time a saber quando a resposta automatica e suficiente ou quando deve chamar uma pessoa.

## Publico

- equipes de suporte tecnico que lidam com perguntas recorrentes
- operacoes que usam WhatsApp, Meta WhatsApp Cloud API ou outros canais
  externos para atendimento
- times que precisam auditar respostas, referencias e falhas
- projetos que querem reaproveitar o mesmo nucleo de agente em varios dominios

## Dores Que Resolve

- respostas repetitivas consumindo tempo do suporte
- variacao de qualidade entre atendentes, turnos ou canais
- bots que inventam resposta quando nao tem contexto
- falta de rastreabilidade sobre o motivo de uma resposta ou escalonamento
- dificuldade de reutilizar a mesma base tecnica em outro setor

## Promessas Do Produto

- responder com base em conhecimento versionado
- preservar contratos claros para integracoes externas
- expor `request_id`, `references`, `confidence`, `handoff_reasons` e `error_code`
- falhar de forma segura quando provider, credencial ou retrieval estiver indisponivel
- escalar para humano quando o contexto for fraco, sensivel, fora de escopo ou explicitamente solicitado
- manter o nucleo reutilizavel por dominio

## O Que Nao Prometer

- autonomia total sem supervisao
- resposta garantida para qualquer assunto
- substituicao definitiva do suporte humano
- acesso automatico a servidores, credenciais, cobranca ou dados privados
- promocao de `pgvector` como padrao permanente antes da calibragem
- uso de Chroma como fonte oficial de producao

## Tom De Comunicacao

Use um tom comercial tecnico: claro, confiavel, operacional e direto.

Prefira:

- "responde com base em conhecimento controlado"
- "escalona quando falta contexto"
- "preserva rastreabilidade para integracoes"
- "preparado para multiplos dominios"

Evite:

- promessas absolutas
- linguagem de hype
- afirmar que o bot resolve tudo sozinho
- esconder limites do MVP

## Mensagem Curta Recomendada

Agente de suporte com RAG para responder duvidas recorrentes de VPS, WhatsApp e automacoes com seguranca, rastreabilidade e escalonamento humano.

## Mensagem De Valor

O `supportFAQagent` transforma conhecimento tecnico versionado em respostas consistentes e auditaveis. Ele reduz perguntas repetidas, preserva referencias e sabe quando escalar para suporte humano.

## Provas Tecnicas

- FastAPI como contrato HTTP
- dominios versionados em `domains/`
- loader GitHub baseado na Contents API oficial para fontes versionadas
- retrieval lexical seguro para local/CI e rollback
- pgvector como default operacional do staging
- fundacao nativa para Meta WhatsApp Cloud API por feature flag
- Hermes documentado apenas como adapter temporario de entrega
- LLM real com fallback seguro
- handoff estruturado
- rate limit no `/chat`
- `X-Request-ID` em todas as respostas
- testes automatizados para contratos, seguranca, retrieval, LLM e handoff

## Como Usar Este Doc

- README: deve vender o valor primeiro e apontar para docs tecnicos depois.
- Docs tecnicos: devem manter precisao, limites e status real do MVP.
- Skills de agentes: devem preservar esse posicionamento ao planejar, testar, commitar ou abrir PRs.
- PRs: devem explicar impacto para produto, seguranca, operacao ou integracao, nao apenas arquivos alterados.
