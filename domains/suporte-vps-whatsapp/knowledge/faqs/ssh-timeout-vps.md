# SSH timeout na VPS

Quando o acesso SSH da VPS falha com timeout no PuTTY ou no terminal, valide primeiro se a VPS esta ligada e se o servico SSH esta ativo.

Checklist inicial:

- confirme se o IP, usuario e porta estao corretos
- teste novamente a porta SSH configurada, normalmente 22
- veja se houve troca de senha, chave SSH ou usuario
- confirme se o firewall da VPS ou da hospedagem nao bloqueou a porta
- verifique se a VPS esta com CPU, memoria ou disco no limite
- se houver painel da hospedagem, use o console web para testar acesso interno

Casos comuns relacionados:

- se voce cadastrou uma chave SSH e a VPS continua pedindo senha, revise o usuario usado na conexao, permissoes do arquivo `authorized_keys` e se a chave publica correta foi aplicada
- se aparece `permission denied (publickey)`, valide se a chave privada corresponde a chave publica cadastrada e se o servidor aceita autenticacao por chave para aquele usuario
- se voce mudou a porta do SSH ou alterou o firewall e perdeu acesso, o caminho mais seguro e validar a regra pelo console web do provedor antes de insistir em novas tentativas

Se o servico estiver ativo, mas o timeout continuar, o caso deve ser escalado para humano ou infraestrutura, porque pode envolver rede, firewall, bloqueio de IP ou indisponibilidade do servidor.
