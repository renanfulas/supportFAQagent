# Como migro meu site para a hospedagem sem tirar do ar

Use este artigo quando a duvida e migrar um site para a hospedagem da HostGator
sem tirar o site do ar durante a troca.

A ordem segura e subir e testar tudo antes de mexer no DNS:

- transfira os arquivos por FTP do provedor antigo para a hospedagem nova,
  mantendo a mesma estrutura de pastas
- exporte o banco de dados pelo phpMyAdmin antigo, crie o banco na HostGator e
  importe o arquivo
- atualize o arquivo de configuracao do site com os novos dados de banco
- teste o site no servidor novo usando o arquivo hosts do seu computador, antes
  de trocar o DNS
- so depois de confirmar que tudo abre, troque o DNS do dominio para a HostGator

Checklist inicial:

- tenha o plano novo ja ativo e um cliente de FTP como o FileZilla
- a propagacao do DNS leva ate 24 horas
- o SSL configura automaticamente se o dominio estiver registrado na HostGator

Quando escalar para humano:

- prefere que o suporte faca a restauracao dos arquivos em vez do FTP manual
- o site novo nao funciona igual ao antigo nos testes pelo arquivo hosts
