# Mapeamento das categorias do suporte HostGator

Origem: https://suporte.hostgator.com.br/hc/pt-br/categories/30807008626707 e as
16 categorias irmas listadas na mesma Central de Ajuda. Cada categoria foi
aberta e os titulos de artigo foram inventariados (sem copiar corpo de
artigo nem dado de cliente) para decidir o que entra no escopo do dominio
`suporte-vps-whatsapp` (VPS, Evolution API, WhatsApp, n8n, webhooks,
automacoes, conforme `domains/suporte-vps-whatsapp/domain.yaml`).

## Como ler esta tabela

- **Dentro do escopo**: a intencao foi adicionada como caso de descoberta em
  `evals/intake/vps_support_faq_hostgator_real.yaml` quando nao havia
  equivalente proximo no banco sintetico existente (`vps_support_faq_100.yaml`
  a `vps_support_faq_901_1000.yaml`).
- **Fora do escopo**: a intencao foi adicionada como caso de confinamento em
  `evals/confinement/out_of_scope.yaml`, porque pertence a outro produto
  HostGator (conta, dominio/registro, e-mail, criador de site, afiliados) e
  nao a operacao tecnica de VPS/WhatsApp/automacoes.
- **Ja cobertos**: a categoria existente do banco sintetico (`dns_dominios`,
  `email_smtp`, `painel_whm_cpanel`, `backup_restore`, `banco_dados`, etc.) ja
  trata a mesma intencao quando ela e reformulada como operacao "na minha
  VPS" — esses casos nao foram duplicados.

## Categorias

| Categoria HostGator | Classificacao | Observacao |
| --- | --- | --- |
| Primeiros Passos | Fora do escopo | Onboarding geral (criar site, restaurar backup completo, contato com suporte) nao especifico de VPS/WhatsApp. |
| Minha Conta | Fora do escopo | Financeiro, PayPal, cadastro/senha do Portal do Cliente, Indique e Ganhe. Mesma familia do caso `confinement-fora-do-escopo-financeiro` ja existente. |
| Inteligencia Artificial (SuperGator / Agentes de IA) | Fora do escopo | Produto proprio da HostGator que tambem "conecta ao WhatsApp" (SuperGator), mas e um agente de IA hospedado pela HostGator, nao a stack Evolution API/n8n que este dominio suporta. Risco real de confusao -> caso dedicado em out_of_scope.yaml. |
| Painel cPanel | Ja cobertos / Fora do escopo | Acesso e administracao do cPanel **na VPS** ja esta no banco (`painel_whm_cpanel`). Dominios/subdominios, e-mail e .htaccess de hospedagem compartilhada genericos ficam fora. |
| Dominio & DNS | Ja cobertos / Fora do escopo | Apontar dominio/zona DNS **para a VPS** ja esta no banco (`dns_dominios`). Registro, transferencia, EPP e suspensao ICANN sao comerciais de registrador -> fora do escopo. |
| Produtos (planos compartilhados, Revenda, SiteLock, Weebly etc.) | Fora do escopo | Planos de hospedagem compartilhada e produtos legados/descontinuados, nao VPS. |
| E-mail Titan | Fora do escopo | Plataforma de e-mail SaaS propria (calendario, contatos, campanhas). Distinta de "minha VPS nao envia e-mail" (isso ja esta em `email_smtp`). |
| E-mail cPanel | Fora do escopo | Configuracao de clientes de e-mail (Outlook, Gmail, Horde, Roundcube) para hospedagem compartilhada. |
| **VPS e Dedicados** | Dentro do escopo | Categoria central. KVM, planos VPS Linux vs VPS n8n, AlmaLinux 9, paineis nomeados (CyberPanel/EasyPanel/Virtualmin/Webmin/Plesk), OpenClaw, Evolution CRM vs Evolution API, upgrade/gerenciamento de VPS, Servidor Dedicado. Fonte principal de `vps_support_faq_hostgator_real.yaml`. |
| Criador de Sites | Fora do escopo | Site builder com IA, blog e loja do Criador de Sites. |
| Ferramenta WordPress | Fora do escopo | Instalacao/gestao de WordPress, temas, plugins, WooCommerce. |
| WHM | Ja cobertos / Dentro do escopo | Acesso e contas do WHM **na VPS** ja estao no banco (`painel_whm_cpanel`). Conta de revenda e troca de licenca cPanel via WHM foram adicionadas como descoberta nova. |
| Seguranca (Gator Backup, Gator Protect, SiteLock, SSL) | Fora do escopo / Dentro do escopo | Produtos pagos de backup/anti-malware (Gator Backup, Gator Protect, SiteLock) sao comerciais -> fora do escopo. ModSecurity/WAF **na VPS** e tecnico e foi adicionado como descoberta nova; SSL generico ja esta em `webserver_ssl`. |
| Aplicacoes e Ferramentas Externas | Fora do escopo (maioria) | WHMCS, Joomla, Magento, FileZilla, Cloudflare CDN, Asaas, Link na Bio e Google Search Console sao produtos/integracoes fora do escopo. Acesso a banco de dados (MySQL/PostgreSQL) ja esta cobeto via `banco_dados`. |
| Especificacoes dos Servidores | Dentro do escopo (parcial) | Codigos de erro reais (500, 503, 522 Cloudflare, ERR_TOO_MANY_REDIRECTS) adicionados como descoberta nova em `indisponibilidade_incidente`/`webserver_ssl`. Limites genericos de hospedagem compartilhada ficaram fora. |
| Programa de Afiliados | Fora do escopo | Programa comercial de indicacao, nao suporte tecnico. |
| Construtor de Sites Avancado (descontinuado) | Fora do escopo | Produto legado de site builder. |

## Arquivos afetados

- `domains/suporte-vps-whatsapp/evals/intake/vps_support_faq_hostgator_real.yaml`:
  18 casos novos de descoberta, todos com `expected_references: []` (ainda
  nao promovidos; promover apenas depois de escrever/apontar artigo real,
  seguindo `docs/runbooks/anonymous-eval-intake.md`).
- `domains/suporte-vps-whatsapp/evals/confinement/out_of_scope.yaml`: 8 casos
  novos cobrindo as categorias classificadas como fora do escopo acima.
