# Roadmap de arquitetura de dominios

Documento de alinhamento sobre como o produto se divide em dominios e para onde
vai cada tema do suporte HostGator. Serve para decidir o que construir sem
atropelar outra frente. Nao e um compromisso de implementar tudo; e o mapa que
diz qual e o proximo passo seguro e quem precisa ser envolvido.

Fontes relacionadas: `docs/architecture/architecture.md`, `docs/architecture/domain-contract.md`,
`docs/architecture/domain-evals.md`,
`domains/suporte-vps-whatsapp/evals/intake/hostgator-categories-mapping.md`.

## Dominios atuais

| Dominio | Papel | Estado | Owner |
| --- | --- | --- | --- |
| `suporte-vps-whatsapp` | Suporte tecnico de VPS com foco em WhatsApp, Evolution API, n8n, webhooks e automacoes | Vivo, no roteador, base de conhecimento real | Renan |
| `vendas` | Comercial consultivo (VPS e Hospedagem): qualificar, recomendar plano, conduzir fechamento | Vivo, no roteador, base de conhecimento real | Comercial |
| `suporte-vps` | Gerenciamento e ciclo de vida de VPS/Dedicado pelo Portal do Cliente (o que e VPS/KVM, reinstalacao de SO, painel/aplicacao, upgrade, acesso RDP), distinto da camada de automacao | Fase 1, no roteador (provider openai) | Renan |
| `suporte-hospedagem` | Suporte tecnico de Hospedagem de Sites compartilhada (cPanel, e-mail, WordPress, DNS do site, SSL, banco) | Fase 1, no roteador (provider openai) | Renan |

Os quatro dominios estao em `WHATSAPP_ROUTER_DOMAINS`
(`suporte-vps-whatsapp,vendas,suporte-hospedagem,suporte-vps`). O roteador segue
desligado por `ENABLE_WHATSAPP_DOMAIN_ROUTER=false` ate o ops ativar.

## Fronteira entre `suporte-vps` e `suporte-vps-whatsapp`

A separacao e por camada:

- `suporte-vps`: gerenciamento/ciclo de vida do **servidor** pelo Portal do
  Cliente - o que e VPS/KVM, reinstalacao (rebuild) de SO, painel/aplicacao,
  upgrade de plano, acesso ao Dedicado (RDP).
- `suporte-vps-whatsapp`: a **operacao** da camada de automacao/mensagem que roda
  sobre a VPS - Evolution API, n8n, webhooks, QR Code, disparo, risco de bloqueio,
  alem do troubleshooting de runtime (SSH, performance, queda).

### Roteamento por keyword unica

Termos como `vps` aparecem em varios dominios. O roteador usa **unique-keyword
routing** (`DomainRouter._match_keywords`): qualquer keyword presente em 2+
dominios e tratada como vocabulario *ambiente* e ignorada no roteamento; so
keywords exclusivas de um dominio decidem. Assim `vps` (compartilhado) nao gera
empate, e os discriminadores roteiam - `reinstalar`/`rebuild`/`rdp`/`kvm` ->
`suporte-vps`; `evolution`/`n8n`/`qrcode`/`ssh` -> `suporte-vps-whatsapp`. Uma
mensagem so com termo ambiente cai no fallback conversacional (saudacao ou
pergunta de esclarecimento - fallback seguro). Isso e apenas de
roteamento: a mesma keyword compartilhada continua sendo sinal valido de escopo
dentro de um dominio ja escolhido (`HandoffService._has_domain_signal`).

Fronteiras conhecidas (caem no fallback de esclarecimento, por seguranca):
frase so com `vps`;
`servidor dedicado` vs a ancora comercial `servidor` do `vendas`; `<tema> da
hospedagem` vs a ancora `hospedagem`. Cobertas por testes em
`tests/test_domain_router.py`. Um dominio cujas keywords sejam todas
compartilhadas so seria alcancavel por selecao explicita (numero/nome).

## Destino de cada bloco do suporte HostGator

Resumo do mapeamento completo em
`domains/suporte-vps-whatsapp/evals/intake/hostgator-categories-mapping.md`.

| Bloco | Destino | Pre-requisito |
| --- | --- | --- |
| cPanel, e-mail cPanel, WordPress, DNS de apontamento, SSL do site, MySQL/phpMyAdmin, FTP, .htaccess, PHP, cron, Criador de Sites, erros de site (404/500/503/522) | `suporte-hospedagem` | Base de conhecimento real (Fase 1) |
| O que e VPS/KVM, reinstalacao de SO, adicionar painel/aplicacao, upgrade de plano, acesso ao Dedicado (RDP) | `suporte-vps` | Base de conhecimento real (Fase 1) |
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
- **Fase 2 (feita, proposta ao Comercial):** podadas as genericas tecnicas de
  `vendas` (`site`, `ssl`, `email`, `dominio`, `wordpress`, `migracao`, `migrar`);
  mantidos `hospedagem`/`vps`/`servidor` como ancoras comerciais. `suporte-vps` e
  `suporte-hospedagem` registrados em `WHATSAPP_ROUTER_DOMAINS` (roteador segue
  desligado por `ENABLE_WHATSAPP_DOMAIN_ROUTER=false` ate o ops ativar). A colisao
  de vocabulario VPS entre `suporte-vps` e `suporte-vps-whatsapp` foi resolvida
  com unique-keyword routing (ver "Roteamento por keyword unica" acima), nao mais
  por decisao de produto pendente. Eval de regressao com os configs reais em
  `tests/test_domain_router.py`. Owner: Renan + Comercial.
- **Fase 3 (precisa de Alexandre/Silotto):** ingestao no pgvector, suites
  `pgvector_gate`/`pgvector_curated`, provider real e flag de deploy. Owner:
  Renan + Alexandre + Silotto.

## Riscos abertos

- A poda de keywords do `vendas` e uma proposta que ainda precisa do aval do
  Comercial (owner do dominio), embora coberta por eval de regressao.
- Sobreposicao de escopo entre `suporte-vps` e `suporte-vps-whatsapp`: manter a
  fronteira por camada acima e nao duplicar conhecimento.
- Selecao explicita por rotulo so usa a primeira palavra do display; com varios
  dominios "Suporte ...", a selecao confiavel e pelo numero. Por isso o
  `suporte-vps` usa display "Gerenciamento de VPS e Dedicado".
- Conteudo e o gargalo real, nao o codigo: dominio sem base de conhecimento so
  escala e nao agrega sobre o confinamento.
