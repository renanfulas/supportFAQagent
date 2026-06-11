# SSH permission denied publickey

Use este artigo quando a conexao SSH alcança a VPS, mas retorna
`permission denied (publickey)`.

Checklist inicial:

- confirme que o usuario SSH corresponde ao usuario configurado para a chave
- confirme que a chave privada local corresponde a chave publica cadastrada
- revise as permissoes de `~/.ssh` e `authorized_keys` pelo console seguro do provedor
- confirme se o servico SSH aceita autenticacao por chave para aquele usuario
- teste com modo verboso para identificar qual chave foi oferecida, sem publicar logs ou chaves

Esse erro e diferente de timeout: a rede e o servico responderam, mas a
autenticacao por chave foi recusada.

Escale para infraestrutura quando nao houver console seguro, quando a chave
correta continuar sendo recusada ou quando qualquer ajuste puder remover o
ultimo acesso administrativo disponivel.
