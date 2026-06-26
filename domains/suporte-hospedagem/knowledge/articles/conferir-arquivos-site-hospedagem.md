# Como confiro se os arquivos do site estao na hospedagem

Use este artigo quando a duvida e verificar se existem arquivos do site na
hospedagem, usando o Gerenciador de Arquivos do cPanel.

Passos:

- acesse o cPanel da hospedagem
- abra o Gerenciador de Arquivos
- entre na pasta public_html para o dominio principal, ou na pasta com o nome do
  dominio adicional ou subdominio
- confirme se existe um index.php ou index.html, que e a pagina inicial do site

Checklist inicial:

- em sites WordPress confira tambem wp-admin, wp-includes, wp-content e wp-config
- se nao houver index, o site pode mostrar erro 403 ou pagina em branco
- arquivos acima de 500 MB precisam de FTP em vez do Gerenciador de Arquivos

Quando escalar para humano:

- a pasta public_html esta vazia e voce nao sabe por que
- os arquivos parecem corrompidos ou em local errado
