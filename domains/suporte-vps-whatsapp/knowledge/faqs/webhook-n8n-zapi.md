# Webhook do n8n com Z-API nao funciona

Quando o webhook do n8n com Z-API nao recebe eventos, valide cada ponta separadamente antes de alterar o fluxo.

Checklist inicial:

- teste a URL publica do webhook em uma ferramenta externa como webhook.site
- confirme se o metodo HTTP esperado e o mesmo configurado no n8n
- verifique se o workflow do n8n esta ativo
- confira se a URL usada na Z-API e a URL de producao, nao a URL de teste temporaria
- valide firewall, proxy reverso, TLS e portas abertas na VPS
- confira logs do n8n, do proxy e da aplicacao

Se o webhook.site recebe o evento, mas o n8n nao recebe, o problema tende a estar no endpoint, proxy, firewall ou workflow. Se nem o webhook.site recebe, revise configuracao da Z-API ou origem do evento.
