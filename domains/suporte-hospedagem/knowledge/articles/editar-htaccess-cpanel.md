# Como edito o arquivo .htaccess no cPanel

Use este artigo quando a duvida e editar o arquivo .htaccess do site no cPanel
da hospedagem.

O .htaccess fica oculto, entao primeiro mostre os arquivos ocultos:

- no cPanel, abra o Gerenciador de Arquivos
- em Configuracoes, marque Mostrar arquivos ocultos (dotfiles) e salve
- entre na pasta do dominio (public_html para o dominio principal)
- selecione o .htaccess e clique em Editar, confirmando o aviso
- faca as alteracoes e clique em Salvar alteracoes

Checklist inicial:

- faca um backup do site antes de mexer no .htaccess
- o .htaccess controla como o servidor se comporta; erro de sintaxe derruba o site
- se o site quebrar, renomeie o .htaccess para testar e desfaca a alteracao

Quando escalar para humano:

- o site continua com erro 500 mesmo apos desfazer a alteracao
- ha duvida sobre a regra correta a usar no arquivo
