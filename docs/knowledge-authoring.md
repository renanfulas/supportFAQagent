# Como escrever artigos bons para RAG

Um artigo bom para RAG precisa ser facil de recuperar, facil de resumir e seguro para o agente usar.

## Estrutura recomendada

Use textos curtos, com uma pergunta ou problema por arquivo.

```md
# Problema principal

Explique em uma frase quando esse artigo deve ser usado.

Checklist inicial:

- passo verificavel
- passo verificavel
- passo verificavel

Quando escalar:

- criterio claro de risco
- criterio claro de falta de acesso
```

## Boas praticas

- Use no titulo as palavras que o usuario provavelmente escreveria.
- Inclua sinonimos reais quando fizer sentido, como `QR Code`, `codigo`, `pareamento`.
- Prefira checklists curtos a paragrafos longos.
- Separe problemas diferentes em arquivos diferentes.
- Escreva o suficiente para orientar, nao para substituir um manual inteiro.
- Diga quando o caso deve ser escalado para humano.

## Evite

- Misturar muitos assuntos no mesmo artigo.
- Prometer garantia em temas como bloqueio, banimento, cobranca ou uptime.
- Colocar senhas, tokens, telefones reais, emails pessoais ou chaves de API.
- Escrever respostas finais longas demais dentro do artigo.
- Criar conteudo que contradiz o `domain.yaml`.

## Checklist antes de abrir PR

1. O arquivo esta em `domains/<dominio>/knowledge/`.
2. O titulo descreve o problema com termos reais do usuario.
3. O artigo tem passos verificaveis.
4. O artigo diz quando escalar.
5. Os evals do dominio foram atualizados quando a mudanca altera comportamento esperado.
6. `python -m app.evals.run_domain_eval <dominio>` foi executado.

## Exemplo de bom foco

Bom:

- `ssh-timeout-vps.md`
- `webhook-n8n-zapi.md`
- `risco-bloqueio-whatsapp.md`

Ruim:

- `problemas-gerais.md`
- `manual-completo-whatsapp.md`
- `tudo-sobre-vps.md`
