# Webserver e painel na VPS

Quando Nginx, Apache ou WHM nao respondem, valide primeiro configuracao, porta e conflito de servicos antes de reiniciar em sequencia.

Checklist inicial:

- teste se a porta esperada esta aberta e se outro servico nao ocupou a mesma porta
- confira erro de sintaxe na configuracao do Nginx ou Apache antes de reiniciar
- valide se houve mudanca recente em proxy reverso, SSL, firewall ou redirecionamento
- verifique logs do webserver e do painel
- se o WHM nao carrega, confira a porta padrao do painel, firewall e indisponibilidade geral da VPS

Casos comuns:

- Nginx nao sobe depois de alterar configuracao: revisar sintaxe e ultimo bloco alterado
- Apache nao inicia porque a porta 80 ja esta em uso: identificar qual processo ja ocupa a porta
- WHM nao carrega: testar porta do painel, acesso geral da VPS e regras de firewall

Se a VPS tambem estiver instavel, sem SSH ou com varios servicos indisponiveis ao mesmo tempo, trate como incidente maior e escale.
