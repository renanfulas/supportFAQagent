# n8n na VPS nao abre ou perde conexao

Quando o n8n na VPS nao abre no navegador ou o editor perde conexao, valide separadamente aplicacao, proxy, URL publica e SSL.

Checklist inicial:

- confirme se o servico ou container do n8n esta ativo
- valide se a URL publica aponta para a VPS correta
- confira proxy reverso, HTTPS e portas expostas
- revise variaveis de ambiente do n8n relacionadas a host, protocolo e webhook
- consulte logs do n8n e do proxy para erro de conexao ou websocket

Casos comuns:

- n8n nao abre depois da instalacao: revisar processo ativo, proxy e URL publica
- editor perde conexao com servidor ligado: conferir websocket, proxy e timeout
- falha de webhook por falta de HTTPS: ajustar URL publica e certificado antes de testar de novo

Se o n8n estiver ativo mas a interface continuar indisponivel, investigue proxy, TLS e rede antes de reinstalar.
