# Como adiciono um painel ou aplicacao na minha VPS

Use este artigo quando a duvida e instalar um painel de controle ou uma
aplicacao na VPS pelo Portal do Cliente.

Aplicacoes disponiveis no AlmaLinux 9 incluem cPanel, n8n, WordPress (1-clique),
Docker, Moodle, Node.js, WooCommerce, Laravel e Kubernetes. O OpenClaw exige
Ubuntu 22.04. Nao da para ter cPanel e n8n ao mesmo tempo.

Passos:

- no Portal do Cliente, abra VPS e Dedicados e clique em Gerenciar na VPS NVMe
- em SO, painel e aplicacoes, clique em Alterar SO, painel ou aplicacoes
- selecione Aplicacao e escolha a desejada
- informe um dominio ativo quando exigido (WordPress, WooCommerce)
- marque a confirmacao de remocao dos dados do servidor e clique em Instalar agora
- aguarde o redirecionamento e confirme a instalacao em Gerenciamento

Atencao: esse processo reinstala o sistema. Faca backup completo da VPS antes.

Quando escalar para humano:

- precisa de cPanel e n8n juntos, o que nao e suportado
- a instalacao nao conclui mesmo apos o processo no Portal
