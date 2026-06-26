# Roadmap de arquitetura de dominios

Documento de alinhamento sobre como o produto se divide em dominios e para onde
vai cada tema do suporte HostGator. Serve para decidir o que construir sem
atropelar outra frente. Nao e um compromisso de implementar tudo; e o mapa que
diz qual e o proximo passo seguro e quem precisa ser envolvido.

Fontes relacionadas: `docs/architecture.md`, `docs/domain-contract.md`,
`docs/domain-evals.md`,
`domains/suporte-vps-whatsapp/evals/intake/hostgator-categories-mapping.md`.

## Dominios atuais

| Dominio | Papel | Estado | Owner |
| --- | --- | --- | --- |
| `suporte-vps-whatsapp` | Suporte tecnico de VPS com foco em WhatsApp, Evolution API, n8n, webhooks e automacoes | Vivo, no roteador, base de conhecimento real | Renan |
| `vendas` | Comercial consultivo (VPS e Hospedagem): qualificar, recomendar plano, conduzir fechamento | Vivo, no roteador, base de conhecimento real | Comercial |
| `suporte-vps` | Gerenciamento e ciclo de vida de VPS/Dedicado pelo Portal do Cliente (o que e VPS/KVM, reinstalacao de SO, painel/aplicacao, upgrade, acesso RDP), distinto da camada de automacao | Fase 1 (base real, provider openai, fora do roteador) | Renan |
| `suporte-hospedagem` | Suporte tecnico de Hospedagem de Sites compartilhada (cPanel, e-mail, WordPress, DNS do site, SSL, banco) | Fase 1 (base de conhecimento real, provider openai, fora do roteador) | Renan |

`suporte-vps` e `suporte-hospedagem` estao **fora** de `WHATSAPP_ROUTER_DOMAINS`
(default `suporte-vps-whatsapp,vendas`). Eles carregam e aparecem em `GET /domains`,
mas nao recebem trafego roteado ate a Fase 2.

## Fronteira entre `suporte-vps` e `suporte-vps-whatsapp`

A separacao e por camada, nao por palavra:

- `suporte-vps`: o **servidor** em si - SSH, CPU/memoria/disco, webserver
  (Nginx/Apache), painel, backup, sistema operacional.
- `suporte-vps-whatsapp`: a camada de **automacao/mensagem** que roda sobre a VPS -
  Evolution API, n8n, webhooks, QR Code, disparo, risco de bloqueio.

Termos como `vps` e `docker` aparecem nos dois. Como nenhum roteia hoje, nao ha
colisao ativa; quando um deles entrar no roteador, a desambiguacao tem que ser
por contexto (presenca de `whatsapp`/`evolution`/`n8n` puxa para o dominio de
automacao).

## Destino de cada bloco do suporte HostGator

Resumo do mapeamento completo em
`domains/suporte-vps-whatsapp/evals/intake/hostgator-categories-mapping.md`.

| Bloco | Destino | Pre-requisito |
| --- | --- | --- |
| cPanel, e-mail cPanel, WordPress, DNS de apontamento, SSL do site, MySQL/phpMyAdmin, FTP, .htaccess, PHP, cron, Criador de Sites, erros de site (404/500/503/522) | `suporte-hospedagem` | Base de conhecimento real (Fase 1) |
| SSH, performance/recursos, webserver/painel na VPS, backup do servidor, sistema operacional, paineis (CyberPanel/Webmin/Plesk) | `suporte-vps` | Base de conhecimento real (Fase 1) |
| VPS com Evolution API/CRM, n8n, webhooks, QR Code, automacoes de WhatsApp | `suporte-vps-whatsapp` (ja cobre) | - |
| Contratacao, preco, upgrade, Revenda, Gator Backup, Gator Protect, SiteLock, Afiliados, Indique e Ganhe, registro/transferencia de dominio | `vendas` | Avaliar ampliar base comercial |
| Fatura, PayPal, Pix, DDA, 2FA do Portal, recuperar acesso, dados cadastrais, renovacao | Escalonamento humano (politica `sensitive_terms` + `escalate_on: billing`) | Nao vira dominio enquanto for "tudo escala" |
| SuperGator / Agentes de IA da HostGator, e-mail Titan | Produto separado (fora por ora) | Decisao de produto |
| Cloudflare, WHMCS, FileZilla, Joomla/Magento, Asaas, Search Console | Integracoes de terceiros (prioridade baixa) | Sinal de demanda |
| Weebly, Construtor Avancado, CodeGuard, Pagina Facil, G Suite | Legado/descontinuado | Ignorar |

## Fases

- **Fase 0 (feita):** esqueletos `suporte-vps` e `suporte-hospedagem` com
  `provider: mock`, confinamento verde. Fora do roteador. Risco zero para os
  dominios vivos. Owner: Renan.
- **Fase 1 (feita para `suporte-hospedagem` e `suporte-vps`):** bases de
  conhecimento reais reaproveitadas da Central de Ajuda HostGator e parafraseadas
  no formato do projeto; provider `openai`; evals in-scope validando retrieval no
  padrao deterministico dos dominios vivos. `suporte-hospedagem`: 14 artigos/FAQs
  (cPanel, e-mail, WordPress, DNS, SSL, backup, arquivos, migracao, MySQL, FTP,
  .htaccess, PHP, cron, erro 500). `suporte-vps`: 5 artigos (o que e VPS/KVM,
  rebuild de SO, painel/aplicacao, upgrade, acesso RDP do Dedicado). Owner:
  Renan + autoria.
- **Fase 2 (feita para `suporte-hospedagem`, proposta ao Comercial):** podadas as
  genericas tecnicas de `vendas` (`site`, `ssl`, `email`, `dominio`, `wordpress`,
  `migracao`, `migrar`); mantidos `hospedagem`/`vps`/`servidor` como ancoras
  comerciais. `suporte-hospedagem` registrado em `WHATSAPP_ROUTER_DOMAINS`
  (roteador segue desligado por `ENABLE_WHATSAPP_DOMAIN_ROUTER=false` ate o ops
  ativar). Eval de regressao em `tests/test_domain_router.py`. Fronteira conhecida:
  uma frase tecnica que so cite "hospedagem"/"vps" (sem termo de compra nem termo
  tecnico distintivo) empata e cai no menu, fallback seguro. `suporte-vps` ainda
  NAO entra no roteador por colidir no vocabulario de VPS com
  `suporte-vps-whatsapp` (decisao de produto pendente). Owner: Renan + Comercial.
- **Fase 3 (precisa de Alexandre/Silotto):** ingestao no pgvector, suites
  `pgvector_gate`/`pgvector_curated`, provider real e flag de deploy. Owner:
  Renan + Alexandre + Silotto.

## Riscos abertos

- Colisao de keywords entre `suporte-hospedagem` e `vendas` (resolver na Fase 2,
  com o Comercial; nao adicionar ao roteador antes disso).
- Sobreposicao de escopo entre `suporte-vps` e `suporte-vps-whatsapp`: manter a
  fronteira por camada acima e nao duplicar conhecimento.
- Conteudo e o gargalo real, nao o codigo: dominio sem base de conhecimento so
  escala e nao agrega sobre o confinamento.
