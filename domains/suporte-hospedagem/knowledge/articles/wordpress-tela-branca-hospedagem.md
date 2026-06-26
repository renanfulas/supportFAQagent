# WordPress abre uma tela branca na hospedagem

Use este artigo quando o site WordPress da hospedagem abre uma tela branca, sem
mensagem de erro visivel.

A tela branca do WordPress costuma vir de plugin, tema ou limite de memoria.

Checklist inicial:

- desative os plugins do WordPress pelo cPanel ou pelo phpMyAdmin e teste o site
- troque temporariamente o tema ativo por um tema padrao do WordPress
- aumente o limite de memoria do WordPress no wp-config.php
- confira o log de erros da hospedagem no cPanel para achar a causa

Quando escalar para humano:

- a tela branca continua mesmo apos desativar plugins e trocar o tema
- o log aponta erro de banco de dados ou de configuracao do servidor
