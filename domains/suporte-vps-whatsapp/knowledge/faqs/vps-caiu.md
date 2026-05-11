# O que fazer quando a VPS caiu

Quando a VPS cai, o primeiro passo e diferenciar problema do servidor, da aplicacao ou de rede.

Checklist rapido:

- acesse o painel da hospedagem e confirme se a VPS esta ligada
- verifique uso de CPU, memoria, disco e reinicios recentes
- teste `GET /health` da aplicacao, se ela ja estiver publicada
- tente acessar por SSH ou console web
- confira logs dos containers Docker, proxy reverso e aplicacao
- veja se houve mudanca recente em DNS, firewall, portas ou variaveis de ambiente

Se a VPS nao responde nem por SSH nem pelo console da hospedagem, escale para infraestrutura. Se a VPS responde, mas a aplicacao nao, investigue containers, portas, logs e variaveis.
