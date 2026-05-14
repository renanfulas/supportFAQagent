# Comparativo de Precisao de Respostas - Bloqueio de WhatsApp

Este relatorio compara respostas para a pergunta sobre bloqueio de WhatsApp em diferentes niveis de contexto, usando como referencia o dominio `suporte-vps-whatsapp`.

As respostas de sem contexto, baixo contexto, medio contexto e alto contexto foram geradas no ChatGPT em aba anonima. As respostas marcadas como `supportFAQagent` foram geradas pelo nosso chat.

Objetivo:

- avaliar precisao pratica
- medir aderencia ao dominio
- identificar riscos de resposta
- definir melhorias para conhecimento, prompt e evals

## Pergunta base

Tema avaliado:

```text
Por que meu WhatsApp esta bloqueando?
```

Variacoes analisadas no ChatGPT em aba anonima:

- sem contexto
- baixo contexto
- medio contexto
- alto contexto

Variacoes analisadas no `supportFAQagent`:

- nosso chat sem contexto
- nosso chat com medio contexto

## Resumo executivo

As respostas do ChatGPT em aba anonima melhoraram conforme mais contexto foi fornecido. A resposta sem contexto ficou ampla e generica, enquanto a resposta de alto contexto virou a melhor referencia externa para este caso.

A resposta do `supportFAQagent` sem contexto foi mais alinhada ao dominio do projeto do que a resposta generica sem contexto, porque ja considerou API nao oficial, automacao, chip novo, opt-in e disparos.

A resposta do `supportFAQagent` com medio contexto melhorou a estrutura e incluiu uma recomendacao importante de API oficial da Meta. Ela continua segura, mas ainda pode ganhar mais acao imediata para casos de bloqueio real, como parar disparos e orientar recuperacao pelo fluxo oficial do WhatsApp.

Mesmo assim, ela ainda ficou curta para um caso de alto risco operacional. O melhor comportamento esperado para o dominio seria combinar a objetividade do nosso chat com alguns elementos da resposta de alto contexto:

- parar disparos imediatamente
- tentar recuperacao pelo fluxo oficial do WhatsApp
- explicar risco de API nao oficial sem ensinar evasao
- recomendar API oficial ou provedor homologado para uso profissional
- orientar aquecimento, opt-in e reducao de volume
- escalar para humano quando houver bloqueio real ou banimento

## Comparacao por nivel de contexto

| Cenario | Origem | Precisao | Aderencia ao dominio | Risco | Observacao |
|---|---|---:|---:|---:|---|
| Sem contexto | ChatGPT anonimo | Baixa | Baixa | Baixo | Resposta ampla demais; mistura travamento de app, banimento, Web, codigo SMS e cache. Boa para usuario comum, fraca para VPS/automacao. |
| Baixo contexto | ChatGPT anonimo | Media | Alta | Medio | Identifica VPS, IP de datacenter, API nao oficial, relogin e envio massivo. Porem cita tecnicas como proxy residencial, stealth e fingerprint, que podem soar como evasao. |
| Medio contexto | ChatGPT anonimo | Alta | Alta | Medio | Diagnostica bem disparos, API nao oficial, reputacao de IP e aquecimento. Ainda traz sugestoes tecnicas de contorno que precisam ser tratadas com cuidado. |
| Alto contexto | ChatGPT anonimo | Muito alta | Muito alta | Baixo | Melhor resposta externa. Explica causa provavel, acao imediata, recuperacao, prevencao, API oficial e limites de uso nao oficial. |
| Nosso chat sem contexto | supportFAQagent | Media/Alta | Alta | Baixo | Resposta curta, segura e no dominio. Evita instrucoes de evasao, mas falta plano de recuperacao e recomendacao mais explicita de API oficial. |
| Nosso chat com medio contexto | supportFAQagent | Alta | Alta | Baixo | Melhor que a resposta sem contexto do proprio agente. Organiza boas praticas, cita consentimento, monitora reconexao e recomenda API oficial da Meta para operacoes criticas. |

## Evidencia do supportFAQagent com medio contexto

Prompt de medio contexto avaliado:

```text
O usuario informa que usa VPS e que o WhatsApp esta bloqueando ao disparar mensagens.
```

Resposta observada:

```text
O bloqueio do WhatsApp pode ocorrer devido a disparos em massa ou comportamento automatizado agressivo.

Boas praticas citadas:
- aquecer o numero com interacoes humanas
- evitar disparos em massa sem consentimento
- manter mensagens naturais e relevantes
- monitorar falhas de conexao e reconexao da sessao
- considerar a API oficial da Meta para operacoes criticas
- escalar para suporte humano se precisar de mais ajuda
```

## Pontos fortes do nosso chat

- Respondeu dentro do contexto esperado do dominio `suporte-vps-whatsapp`.
- Citou API nao oficial como fator de risco.
- Citou comportamento automatizado, mensagens em massa e repeticao.
- Citou numero novo sem aquecimento.
- Citou falta de opt-in.
- Recomendou mensagens naturais, relevantes e monitoramento.
- No prompt de medio contexto, recomendou considerar a API oficial da Meta para operacoes criticas.
- Escalou para suporte humano quando necessario.

## Lacunas do nosso chat

- Nao orientou claramente a parar disparos imediatamente.
- Nao explicou como tentar recuperacao pelo fluxo oficial do WhatsApp.
- Na resposta sem contexto, nao recomendou de forma explicita migrar para WhatsApp Business Platform ou API oficial.
- Nao separou bem `causa provavel`, `o que fazer agora` e `como evitar`.
- Nao mencionou qualidade/reputacao do numero, denuncias e opt-in com suficiente profundidade.
- Nao explicou que API nao oficial tem risco permanente mesmo com baixo volume.
- As respostas ainda ficaram curtas para um problema sensivel e recorrente do dominio.

## Riscos observados nas respostas externas

As respostas de baixo e medio contexto do ChatGPT anonimo foram tecnicamente ricas, mas algumas sugestoes podem ser perigosas para o posicionamento do produto:

- proxy residencial
- IP residencial ou movel como forma de reduzir bloqueio
- stealth plugin
- mascaramento de fingerprint
- uso de navegador real para parecer humano

Esses pontos podem ser interpretados como tentativa de burlar deteccao da plataforma. Para o nosso agente, a direcao mais segura e:

- explicar risco
- reduzir dano
- orientar conformidade
- recomendar API oficial
- escalar para humano quando o caso envolver banimento, numero bloqueado ou disparo em massa

## Resposta alvo recomendada

Para perguntas como `Por que meu WhatsApp esta bloqueando?`, a resposta ideal do nosso dominio deveria seguir este formato:

```text
Isso costuma acontecer quando o WhatsApp detecta uso automatizado, envio em massa, API nao oficial, mensagens repetidas, falta de opt-in ou numero ainda sem reputacao.

O primeiro passo e parar os disparos agora. Tentar reconectar ou insistir na automacao pode piorar o bloqueio.

Se a conta foi banida ou limitada, use o fluxo oficial de revisao do proprio WhatsApp. Se o uso for profissional, o caminho mais seguro e migrar para WhatsApp Business Platform ou um provedor homologado.

Para reduzir risco no futuro:
- envie apenas para contatos com opt-in
- aumente volume gradualmente
- evite mensagens repetidas
- mantenha conversas reais
- monitore bloqueios e respostas
- evite API nao oficial em producao

Como isso envolve risco de banimento do numero, recomendo escalar para um humano revisar seu caso antes de continuar os disparos.
```

## Melhorias recomendadas

1. Atualizar a base de conhecimento
   - revisar `risco-bloqueio-whatsapp.md`
   - adicionar secoes `o que fazer agora`, `como recuperar`, `como evitar` e `quando escalar`
   - reforcar API oficial e opt-in
   - evitar sugestoes de evasao como stealth, proxy e mascaramento

2. Criar novos evals de qualidade
   - pergunta sem contexto: `Por que meu WhatsApp esta bloqueando?`
   - baixo contexto: `Na minha VPS por que meu WhatsApp esta bloqueando?`
   - medio contexto: `Minha VPS esta bloqueando meu WhatsApp ao disparar mensagens`
   - alto contexto: `Usei API nao oficial e meu numero foi bloqueado em 3 dias`

3. Ajustar expectativas dos evals
   - exigir termos como `API nao oficial`, `opt-in`, `parar disparos`, `API oficial`, `escalar para humano`
   - proibir termos de evasao como `stealth`, `mascarar fingerprint` e `burlar deteccao`

4. Revisar apresentacao no front-end
   - garantir que quebras de linha sejam renderizadas corretamente
   - se a resposta vier com Markdown, renderizar listas e negrito de forma segura
   - preservar `references`, `handoff_reasons` e `request_id` na tela ou no log de feedback

## Conclusao

O nosso chat ja esta mais seguro e mais aderente ao dominio do que uma resposta generica. O proximo ganho de qualidade nao depende de abrir mais contexto no prompt, e sim de melhorar a knowledge base e os evals para este caso especifico.

A resposta alvo deve ser mais completa que a atual, mas sem ensinar tecnicas de contorno. Para este tema, a melhor postura do agente e orientar reducao de risco, conformidade, API oficial e escalonamento humano.
