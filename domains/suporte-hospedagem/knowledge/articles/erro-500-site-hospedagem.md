# Como resolvo o erro 500 no site da hospedagem

Use este artigo quando o site hospedado mostra erro 500 (Internal Server Error).

Causas comuns e o que checar:

- atualize a pagina e aguarde 1 a 2 minutos; o servidor pode estar sobrecarregado
- permissoes erradas: arquivos em 644 e pastas em 755; nunca use 777
- .htaccess com erro: renomeie o arquivo para testar e veja se o site volta
- limite de memoria do PHP estourado em sites maiores
- em WordPress, desative os plugins e reative um a um para achar o culpado
- veja o log de erros no cPanel para identificar a causa exata

Checklist inicial:

- faca backup antes de mexer em permissoes, .htaccess ou plugins
- isole uma causa por vez para saber o que resolveu

Quando escalar para humano:

- o erro 500 continua mesmo apos checar permissoes, .htaccess e plugins
- o log aponta erro de banco de dados ou de configuracao do servidor
