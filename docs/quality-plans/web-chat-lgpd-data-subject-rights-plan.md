# Plano - Direitos Do Titular (LGPD)

Status: proposto em 2026-07-27. Nenhuma fase implementada em codigo. Este e o
terceiro item ainda aberto da V3 do chat web listado em
[web-chat-evolution-plan.md](web-chat-evolution-plan.md).

## Contexto E Problema

O projeto ja trata consentimento pontual (gate de contato direto no handoff,
`ENABLE_HANDOFF_CONSENT_GATE`, ver
[customer-identity-whatsapp-handoff-plan.md](customer-identity-whatsapp-handoff-plan.md)),
mas nao existe ainda um fluxo formal para os direitos do titular previstos no
art. 18 da LGPD: confirmacao de tratamento, acesso, correcao,
anonimizacao/eliminacao/bloqueio de dado desnecessario, portabilidade,
informacao sobre compartilhamento e revogacao de consentimento.

Este e, dos tres itens abertos da V3, o de **maior risco de escopo errado**:
diferente do loop feedback->conhecimento e do roteamento multi-dominio (ambos
reaproveitando infraestrutura ja validada e reversivel), aqui a acao alvo
(eliminacao/anonimizacao de dado real) e proxima do irreversivel e tem
consequencia juridica direta. Por isso este documento **so contem plano,
nenhum codigo**: a Fase A abaixo e seguramente implementavel sem revisao
externa (e so um formulario de intake + notificacao, sem apagar nada), mas
recomenda-se validacao de alguem responsavel por compliance/juridico antes de
qualquer fase que efetivamente leia, exporte ou apague dado real de titular —
esse papel nao esta mapeado na tabela de ownership atual do projeto
(`supportfaq-next-step-planner`), então precisa ser trazido explicitamente
antes da Fase B/C.

## Mapa Dos Direitos X Dado Existente

| Direito (art. 18 LGPD) | Dado(s) envolvido(s) | Situacao atual |
| --- | --- | --- |
| Confirmacao de tratamento | `customers`, `verified_identities` | Existe implicitamente (a pessoa sabe que interagiu), sem endpoint formal |
| Acesso aos dados | `customers`, `verified_identities`, `conversations`, `messages`, `support_cases`, `feedback`, `chat_audits` (via `session_hash`) | Nenhum export/consulta self-service |
| Correcao de dado incompleto/incorreto | `customers` (nome, contato) | Sem fluxo; hoje so o time de suporte edita manualmente via banco |
| Anonimizacao/eliminacao/bloqueio de dado desnecessario | mesmas tabelas acima + `web_sessions`, `otp_challenges` | Existe purga automatica por retencao em alguns pontos (ex.: `wa_binding` purga `wa_id` no fechamento/teto de 15 dias, ver `whatsapp-support-bridge-tech-plan.md`), mas nao um "apague meus dados" acionavel pelo titular |
| Portabilidade | mesmos dados de acesso, em formato estruturado | Nao existe |
| Informacao sobre compartilhamento com terceiros | N/A hoje (nenhum compartilhamento com terceiro fora do stack operacional: OpenAI/Anthropic como processador, Meta WhatsApp como canal) | Falta doc publico explicito disso (ver Nao-Objetivos/Fase D) |
| Revogacao de consentimento | `customer_preferences` (opt-out de e-mail ja existe), gate de consentimento do handoff | Parcialmente coberto; falta revogacao geral, nao so por canal |

## Principios (alinhados a `product-positioning.md`)

1. **Nenhuma acao destrutiva automatica sem humano no circuito.** Eliminacao
   real de dado de um titular especifico e o tipo de operacao que este projeto
   trata como "hard-to-reverse": a Fase A cria apenas um pedido durave e
   notifica o time; quem executa a eliminacao de fato, e como, e decisao de
   fase posterior com salvaguarda explicita (ver Fase C).
2. **Reusar, nao duplicar.** O pedido do titular vira um `support_cases` como
   qualquer outro ticket (mesma fila, SLA, auditoria, console do time) --
   nao um canal paralelo de dados.
3. **Prova de titularidade antes de qualquer acao sobre dado real.** Um
   pedido de acesso/eliminacao so pode ser aceito para quem ja passou pelo OTP
   de verificacao (`verified_identities`), no mesmo padrao do gate de
   consentimento -- nunca aceitar telefone digitado sem prova de posse.

## Fases Propostas

### Fase A - Intake durável (seguro, implementavel agora sem revisao externa)

Objetivo: dar ao titular um jeito formal de pedir acesso/correcao/eliminacao/
portabilidade/revogacao, sem executar nenhuma dessas acoes automaticamente.

Fluxo:

```text
Cliente (ja verificado por OTP)
  -> POST /web/privacy/data-request { request_type, note? }
  -> exige sessao com identidade verificada (mesmo gate do handoff)
  -> cria support_cases com:
       priority = "high"
       reason_codes = ["lgpd_<request_type>_request"]
       channel = "web"
       context_snapshot_sanitized = { request_type, note sanitizado }
  -> notifica o time (mesmo canal WhatsApp de novo caso ja existente)
  -> responde { request_id, support_code, eta_message }
```

`request_type` em `{"access", "correction", "deletion", "portability",
"consent_revocation"}`. O atendimento manual do time cumpre o pedido fora do
sistema no MVP (ex.: exportar dado, confirmar eliminacao) -- exatamente como
hoje qualquer escalonamento humano funciona, sem prometer automacao que nao
existe.

Criterios de aceite:

- Endpoint exige identidade verificada (reaproveita `CurrentIdentityResolver`
  e o gate ja usado no handoff); telefone nao verificado recebe erro
  orientando a verificar primeiro.
- Caso criado aparece no console do time (`GET /web/support/cases`) com
  `reason_codes` visivel, dentro do fluxo de fila/SLA/transicoes ja existente
  -- nenhuma tela nova.
- `GET /web/support/metrics` (`escalation_reasons`) passa a contar
  `lgpd_<tipo>_request` organicamente, sem mudanca de schema.
- Nenhum dado e lido, exportado ou apagado automaticamente por este endpoint.
- Dark por padrao (`ENABLE_LGPD_DATA_REQUESTS`), seguindo o padrao do projeto.

### Fase B - Acesso e portabilidade self-service (precisa validacao externa)

Export estruturado (JSON) do que o titular pode ver sobre si mesmo, atras do
mesmo gate de identidade verificada. Antes de implementar: confirmar com
alguem responsavel por compliance qual e o formato aceitavel, o prazo de
resposta e se o export deve ser sincrono (endpoint) ou assincrono (o time
prepara e envia). **Nao iniciar sem essa validacao.**

### Fase C - Eliminacao/anonimizacao acionavel (precisa validacao externa e desenho de salvaguarda)

Eliminacao real de dado de titular e irreversivel por natureza. Antes de
qualquer codigo: decidir com compliance/juridico (a) o que "eliminar" quer
dizer para cada tabela (apagar vs. anonimizar preservando metrica agregada,
como ja acontece com o `wa_id` na ponte WhatsApp), (b) prazo legal de resposta,
(c) confirmacao dupla (ex.: segundo OTP no momento da execucao) para evitar
eliminacao acidental ou por sequestro de sessao. **Nao iniciar sem essa
validacao.**

### Fase D - Documentacao publica de compartilhamento

Atualizar doc publico (README ou doc de privacidade dedicado) explicando que
processadores como o provedor de LLM (OpenAI/Anthropic) e o canal WhatsApp
(Meta) recebem o necessario para operar, sem venda ou compartilhamento com
terceiros alem disso. Baixo risco, pode andar em paralelo com a Fase A.

## Nao-Objetivos (deste plano)

- Nao implementar um "portal de titular" completo (dashboard self-service) no
  MVP -- Fase A e um formulario de intake, nao uma tela de gestao de dados.
- Nao decidir sozinho o formato de eliminacao/anonimizacao (Fase C) sem
  validacao externa -- risco juridico real demais para uma decisao unilateral
  de engenharia.
- Nao misturar este fluxo com o gate de consentimento de contato do handoff
  (proposito diferente: um autoriza contato direto, este exerce um direito
  formal do titular).

## Arquivos Provaveis (Fase A)

- `app/api/routes/web_privacy.py` (novo)
- `app/api/schemas/web_privacy.py` (novo)
- `app/core/config.py` (`enable_lgpd_data_requests`)
- `app/main.py` (router condicional, mesmo padrao do console)
- `docs/architecture/integration-contracts.md` (contrato do endpoint)
- `tests/test_web_privacy.py` (novo)

## Validacao (Fase A)

```bash
python -m pytest
python -m compileall app tests scripts
```

- flag off -> `404`;
- identidade nao verificada -> erro orientando verificacao, nenhum caso criado;
- identidade verificada -> `support_cases` criado com `reason_codes` correto,
  visivel no console;
- nenhuma chamada de eliminacao/exportacao de dado real acontece neste
  endpoint;
- logs sem PII (mesma regra do resto do projeto).

## Dependencias E Sequencia

1. Fase A: nenhuma dependencia externa: implementavel agora.
2. Fase D: pode andar em paralelo com a Fase A.
3. Fase B e Fase C: **bloqueadas** ate um responsavel por
   compliance/juridico validar formato, prazos e salvaguardas -- este papel
   nao existe hoje na tabela de ownership do projeto e precisa ser trazido
   pelo Renan antes de destravar.
