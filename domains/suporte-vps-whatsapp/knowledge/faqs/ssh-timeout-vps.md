# SSH timeout na VPS

Quando o acesso SSH da VPS falha com timeout no PuTTY ou no terminal, valide primeiro se a VPS esta ligada e se o servico SSH esta ativo.

Checklist inicial:

- confirme se o IP, usuario e porta estao corretos
- teste novamente a porta SSH configurada, normalmente 22
- veja se houve troca de senha, chave SSH ou usuario
- confirme se o firewall da VPS ou da hospedagem nao bloqueou a porta
- verifique se a VPS esta com CPU, memoria ou disco no limite
- se houver painel da hospedagem, use o console web para testar acesso interno

Se o servico estiver ativo, mas o timeout continuar, o caso deve ser escalado para humano ou infraestrutura, porque pode envolver rede, firewall, bloqueio de IP ou indisponibilidade do servidor.
