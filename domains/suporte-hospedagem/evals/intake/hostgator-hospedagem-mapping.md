# Intake de hospedagem a partir das categorias HostGator

Este dominio (`suporte-hospedagem`) cobre o cluster tecnico de Hospedagem de
Sites compartilhada. As categorias da Central de Ajuda HostGator que alimentam
a base de conhecimento aqui (classificacao 🏠 no mapeamento geral) sao:

- **Painel cPanel**: acesso, e-mail cPanel, MX/SPF, Softaculous, gerenciador de
  arquivos, permissoes, inodes, banco MySQL/phpMyAdmin, .htaccess, PHP, cron.
- **E-mail cPanel**: clientes externos (Outlook/Gmail), falhas de envio/recebimento,
  POP vs IMAP, Horde/Roundcube, filtros e redirecionamento.
- **Ferramenta WordPress**: instalacao, erro critico, tela branca, painel admin,
  plugins/temas, wp-config, WooCommerce.
- **Dominio & DNS (parte tecnica)**: apontamento, zona DNS, tipos de registro,
  propagacao, URL temporaria - quando aplicado ao site hospedado.
- **Seguranca (parte tecnica)**: SSL gratuito, http->https, aviso de site nao
  seguro, malware/site infectado.
- **Especificacoes dos Servidores (erros de site)**: 404, 500, 503, 522,
  ERR_TOO_MANY_REDIRECTS, ERR_CONNECTION_CLOSED.
- **Criador de Sites** e **Plano WordPress** (operacao do produto).

Fora deste dominio (ver `docs/architecture/domain-architecture-roadmap.md`): VPS/Dedicado,
contratacao/preco, financeiro/conta, produtos de IA (SuperGator) e e-mail Titan.

## Estado

Fase 1: base de conhecimento real com 8 artigos + 2 FAQs parafraseados dos
artigos publicos da Central de Ajuda HostGator (cPanel, e-mail cPanel, WordPress,
DNS, SSL, backup, arquivos do site e migracao). Os casos in-scope em
`evals/cases.yaml` validam o retrieval (`expected_references`) no padrao
deterministico dos dominios vivos.

Proximos passos: ampliar a base com mais temas do cluster (banco MySQL/phpMyAdmin,
FTP, .htaccess, PHP, cron, Criador de Sites, erros de site) e versionar um banco
sintetico amplo de descoberta em `intake/`, seguindo
`docs/runbooks/anonymous-eval-intake.md` e `docs/architecture/knowledge-authoring.md`.
