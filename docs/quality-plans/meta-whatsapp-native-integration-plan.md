# Plano Tecnico - Meta WhatsApp Nativo E Hermes Temporario

Status: planejamento tecnico ativo; Onda 1 implementada em codigo e docs.
Data de revisao: 2026-06-18.

Atualizacao: `n8n` foi removido do projeto. Os assets `deploy/n8n/` e os aliases
legados `N8N_VERIFIED_*_URL` em `app/core/config.py` foram excluidos; somente os
nomes genericos `VERIFIED_*_WEBHOOK_URL` permanecem. As tarefas abaixo que falam
em "manter alias legado n8n" estao concluidas pela remocao e ficam apenas como
registro historico do caminho de migracao.

## Diagnostico

O projeto ja tem o core certo para essa mudanca: `/chat`, handoff, feedback,
persistencia sanitizada, outbox, ingress assinado e `OtpDeliveryAdapter`.
O problema atual esta na borda de integracao: nomes, variaveis e rotas ainda
assumem `n8n` como destino verificado.

Decisao recomendada:

- Meta WhatsApp Cloud API vira o transporte oficial e nativo.
- Hermes pode existir apenas como adapter temporario.
- `n8n` e Evolution ficam como legado/ponte operacional, sem virar contrato
  permanente.

Analogia simples: o backend e o motor do carro. Meta, Hermes, n8n e Evolution
sao cabos que ligam esse motor ao WhatsApp. Vamos trocar o cabo sem abrir o
motor e sem deixar o cabo antigo mandar no volante.

## Prompt Spec Da Entrega

Objetivo:

- Refatorar a camada de entrega externa para separar evento interno de provedor
  externo e preparar uma integracao nativa com Meta WhatsApp Cloud API.

Usuario/downstream:

- Renan para arquitetura, contratos, seguranca, testes e aplicacao.
- Juliano para runtime, VPS, secrets, n8n, Evolution, Hermes e logs externos.

Inputs:

- Contratos atuais em `docs/integration-contracts.md`.
- Observabilidade atual em `docs/observability.md`.
- Codigo atual em `app/api/routes/internal_webhooks.py`,
  `app/core/config.py`, `scripts/dispatch_outbox.py`,
  `app/web_auth/delivery.py` e `app/web_auth/runtime.py`.
- Documentacao oficial Meta sobre Cloud API, webhooks, Message API e
  templates.

Nao objetivos:

- Nao implementar codigo nesta etapa.
- Nao remover n8n/Evolution antes de smoke real.
- Nao mover prompt, RAG, handoff, OTP ou regra de negocio para Hermes, n8n ou
  qualquer provedor externo.
- Nao expor telefone bruto, OTP, token, payload completo ou URL privada em log,
  doc, PR ou teste.

Output esperado:

- Uma refatoracao em fases pequenas.
- Contratos genericos para entrega externa.
- Plano dos modulos Meta nativos.
- Testes e gates antes de ativacao real.

## Estado Atual

Arquivos com acoplamento direto a n8n:

- `app/api/routes/internal_webhooks.py`
  - `EVENT_DELIVERY_TARGET_FIELDS` aponta para os campos genericos
    `verified_handoff_webhook_url`, `verified_whatsapp_webhook_url` e
    `verified_otp_webhook_url`.
  - O endpoint valida assinatura/idempotencia de forma reaproveitavel.
  - O destino verificado deixou de comunicar "n8n" como permanente na Onda 1.

- `app/core/config.py`
  - Contem `VERIFIED_HANDOFF_WEBHOOK_URL`,
    `VERIFIED_WHATSAPP_WEBHOOK_URL` e `VERIFIED_OTP_WEBHOOK_URL`.
  - Os aliases legados `N8N_VERIFIED_*_URL` foram removidos junto com o n8n;
    resta apenas a config generica.
  - `ENABLE_OUTBOX_INGRESS` e `OUTBOX_WEBHOOK_SECRET` ja sao genericos e devem
    ser preservados.

- `scripts/dispatch_outbox.py`
  - `EVENT_URLS` associa evento interno a variavel de URL.
  - O script ja assina payloads e trata retry/dead letter.
  - Ainda falta separar claramente evento de negocio, rota de entrega e
    provedor externo.

Arquivos ja bons para reaproveitamento:

- `app/integrations/webhook_ingress.py`
  - HMAC, payload hash, idempotencia e recibos ja servem para uma fachada
    generica.

- `app/web_auth/delivery.py`
  - `OtpDeliveryAdapter` e o ponto certo para plugar entrega Meta de OTP.

- `app/web_auth/runtime.py`
  - Hoje usa `InMemoryOtpDeliveryAdapter`; deve selecionar adapter por config
    quando a implementacao entrar.

- `app/api/schemas/chat.py`
  - `channel="whatsapp"` ja existe; nao precisa criar canal por provedor na
    primeira versao.

## Arquitetura Alvo

```text
Meta WhatsApp webhook
  -> FastAPI adapter Meta
  -> normalizacao segura do payload
  -> ChatFlowService / contrato equivalente a /chat
  -> resposta do agente
  -> MetaWhatsAppClient
  -> WhatsApp do usuario
```

Fluxo de outbox:

```text
operational_outbox.event_type
  -> dispatcher
  -> delivery route generica
  -> adapter/provider configurado
  -> destino externo
```

Regra de ouro:

- `event_type` descreve o que aconteceu dentro do produto.
- `provider` descreve quem vai entregar fora do produto.
- Nunca misturar esses dois conceitos no nome do contrato.

## Fase 1 - Refatorar Nomes Sem Mudar Comportamento

Status: implementada na Onda 1.

Objetivo:

- Trocar nomes n8n-especificos por nomes genericos mantendo compatibilidade.

Mudancas planejadas:

- Renomear o mapa interno de `EVENT_URL_FIELDS` para algo como
  `EVENT_DELIVERY_TARGET_FIELDS`.
- Criar settings genericos:
  - `VERIFIED_HANDOFF_WEBHOOK_URL`
  - `VERIFIED_WHATSAPP_WEBHOOK_URL`
  - `VERIFIED_OTP_WEBHOOK_URL`
- (Concluido pela remocao do n8n) O alias legado `N8N_VERIFIED_*` foi excluido;
  a config usa apenas os nomes genericos, sem precedencia nem conflito a tratar.
- Atualizar mensagens de erro e logs para `verified_delivery_*`, nao
  `n8n_*`.

Arquivos alvo:

- `app/core/config.py`
- `app/api/routes/internal_webhooks.py`
- `.env.example`
- `docs/integration-contracts.md`
- `docs/observability.md`
- testes de config e ingress interno

Criterio de pronto:

- O nome generico funciona como unica config de destino verificado.
- O alias legado `N8N_VERIFIED_*` foi removido.
- Logs deixam de dizer que o destino verificado sempre e n8n.

## Fase 2 - Separar Evento Interno De Provedor Externo

Status: implementada na Onda 2 para `internal_webhook` e `disabled`; Onda 9
adicionou `meta_whatsapp` para a rota `whatsapp_message` com payload minimo
explicito.

Objetivo:

- Tornar `scripts/dispatch_outbox.py` uma ponte entre eventos internos e rotas
  de entrega, sem acoplar evento a provedor.

Mudancas planejadas:

- Manter eventos atuais:
  - `handoff.requested`
  - `whatsapp.message.requested`
  - `otp.delivery.requested`
- Introduzir resolucao explicita de rota:
  - evento interno;
  - delivery route;
  - provider/transport configurado.
- Documentar modos aceitos:
  - `internal_webhook`: caminho atual assinado para fachada interna.
  - `meta_whatsapp`: caminho nativo para entrega de mensagens WhatsApp pela
    Meta Cloud API.
  - `hermes`: adapter temporario.
  - `disabled`: nao entrega, usado em laboratorio.
- Evitar que `HANDOFF_WEBHOOK_URL`, `WHATSAPP_MESSAGE_WEBHOOK_URL` e
  `OTP_DELIVERY_WEBHOOK_URL` virem nomes de provedor. Eles sao rotas de
  entrega, nao necessariamente n8n.

Arquivos alvo:

- `scripts/dispatch_outbox.py`
- `docs/integration-contracts.md`
- `docs/observability.md`
- testes do dispatcher com envs falsos e HTTP mockado

Criterio de pronto:

- O dispatcher continua entregando o mesmo payload para a fachada interna.
- O teste prova que evento desconhecido nao cai em provedor default.
- O teste prova que URL ausente vira erro observavel e nao vaza payload.
- O teste prova que `meta_whatsapp` so pode ser usado na rota
  `whatsapp_message` e exige `to`/`text` explicitos.

## Fase 3 - Criar Contrato Do Adapter Meta Nativo

Status: fundacao implementada na Onda 3 para `client.py`, `webhook.py`,
`schemas.py` e rota FastAPI. `MetaWhatsAppOtpDeliveryAdapter` implementado na
Onda 4 e pendente de smoke privado. `MetaWhatsAppChatTransport` implementado
na Onda 5 e pendente de smoke privado.

Objetivo:

- Criar a base documentada para implementacao nativa, sem depender de n8n ou
  Hermes para o caminho final.

Modulos planejados:

- `app/integrations/meta_whatsapp/client.py`
  - Cliente HTTP da Graph API.
  - Envia para `/{Phone-Number-ID}/messages`.
  - Usa bearer token privado.
  - Retorna `wamid`, status e erro sanitizado.
  - Timeout curto e erro proprio, sem expor corpo bruto da Meta.

- `app/integrations/meta_whatsapp/webhook.py`
  - Verifica `hub.mode`, `hub.verify_token` e retorna `hub.challenge`.
  - Valida `X-Hub-Signature-256` usando `META_WHATSAPP_APP_SECRET`.
  - Parseia `messages` e `statuses`.
  - Rejeita payload sem shape minimo.
  - Nunca loga payload bruto.

- `app/integrations/meta_whatsapp/schemas.py`
  - Tipos minimos para:
    - inbound text message;
    - delivery/read status;
    - template send request;
    - text send request;
    - erro sanitizado.

- `MetaWhatsAppOtpDeliveryAdapter`
  - Implementa `OtpDeliveryAdapter`.
  - Usa template aprovado para OTP.
  - Nao persiste nem loga OTP puro.
  - Usa `delivery_id` para idempotencia interna.

- `MetaWhatsAppChatTransport`
  - Recebe texto inbound do WhatsApp.
  - Converte para chamada interna do fluxo de chat.
  - Usa `channel="whatsapp"`.
  - Usa identificador de sessao nao bruto, preferencialmente hash chaveado de
    `wa_id`.
  - Envia resposta pelo `MetaWhatsAppClient`.

Settings planejados:

```dotenv
META_WHATSAPP_ACCESS_TOKEN=
META_WHATSAPP_APP_SECRET=
META_WHATSAPP_WEBHOOK_VERIFY_TOKEN=
META_WHATSAPP_WABA_ID=
META_WHATSAPP_PHONE_NUMBER_ID=
META_WHATSAPP_GRAPH_API_VERSION=
META_WHATSAPP_REQUEST_TIMEOUT_SECONDS=5
META_WHATSAPP_OTP_TEMPLATE_NAME=
META_WHATSAPP_OTP_TEMPLATE_LANGUAGE=pt_BR
WHATSAPP_TRANSPORT=meta
WEB_AUTH_OTP_DELIVERY_TRANSPORT=meta
```

Observacao:

- Nao hardcodar versao da Graph API no plano. A versao deve ser confirmada no
  PR de implementacao contra a documentacao oficial vigente.

## Fase 4 - Hermes Como Adapter Temporario

Status: adapter OTP temporario implementado na Onda 6. Chat por Hermes continua
pendente de contrato externo confirmado.

Objetivo:

- Permitir Hermes como ponte sem criar divida tecnica permanente.

Contrato:

- Hermes deve implementar a mesma interface de transporte que Meta.
- Hermes nao pode:
  - chamar banco diretamente;
  - montar prompt;
  - ranquear contexto;
  - decidir handoff;
  - validar OTP;
  - conhecer segredo de hash/persistencia;
  - virar shape publico do `/chat`.
- Hermes pode:
  - normalizar payload externo;
  - entregar mensagem;
  - devolver status de aceite;
  - preservar `request_id`, `delivery_id` e idempotencia.

Feature flags:

```dotenv
WEB_AUTH_OTP_DELIVERY_TRANSPORT=hermes
HERMES_BASE_URL=
HERMES_WEBHOOK_SECRET=
HERMES_REQUEST_TIMEOUT_SECONDS=5
HERMES_OTP_DELIVERY_PATH=/otp-delivery
```

Criterio para remover Hermes:

- Meta webhook verificado em staging.
- Envio de texto Meta validado.
- Template OTP aprovado e testado.
- Fallback e rollback documentados.
- Logs revisados sem PII/secrets.

## Fase 5 - Ativacao Privada E Retirada Do Legado

Status: gates privados implementados com
`scripts/meta_whatsapp_activation_preflight.py`,
`scripts/meta_whatsapp_private_smoke.py` e
`scripts/meta_whatsapp_activation_evidence.py`, com runner consolidado em
`scripts/meta_whatsapp_activation_suite.py`. Smoke real em ambiente privado
continua pendente de secrets, WABA, phone number, template aprovado e runtime.

Sequencia:

1. Implementar refactor generico sem mudar comportamento.
2. Implementar Meta client e webhook com testes unitarios.
3. Ativar `WHATSAPP_TRANSPORT=meta` em ambiente privado.
4. Validar inbound message, outbound text e status webhook.
5. Validar OTP por template aprovado.
6. Manter Hermes/n8n como rollback temporario.
7. Desativar n8n/Evolution somente depois de smoke real e janela de observacao.

Smoke privado minimo:

- Preflight sanitizado confirma configuracao minima por modo sem imprimir
  valores privados.
- Runner consolidado gera preflight, smoke opt-in e evidencia em um diretorio
  unico sem enviar WhatsApp por padrao.
- Preflight cobre tambem `meta-outbox-message` para validar o dispatcher nativo
  de `whatsapp.message.requested`.
- GET de verificacao do webhook retorna `hub.challenge` somente com token certo.
- POST com assinatura invalida retorna rejeicao sem registrar payload.
- Mensagem inbound de texto chama o fluxo de chat em smoke privado opt-in.
- Resposta outbound retorna `wamid`.
- Status `sent`, `delivered`, `read` e `failed` e parseado sem quebrar.
- `whatsapp.message.requested` pode ser entregue pela Meta via dispatcher em
  smoke privado opt-in.
- OTP chega uma unica vez usando template aprovado em smoke privado opt-in.
- Logs nao contem telefone bruto, OTP, token, payload completo ou URL privada.
- Evidencia consolidada indica `ready_for_promotion: true` apenas quando
  modos Meta obrigatorios do preflight, todos os checks Meta obrigatorios de
  smoke e decisao operacional permitem promocao.

## Fontes Oficiais Meta

Use estas fontes antes de implementar, porque nomes, versoes e regras podem
mudar:

- WhatsApp Cloud API oficial no Postman:
  https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api
- Criacao de webhook endpoint:
  https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/create-webhook-endpoint/
- Graph API Webhooks, assinatura e validacao:
  https://developers.facebook.com/docs/graph-api/webhooks/getting-started/
- Message API:
  https://developers.facebook.com/documentation/business-messaging/whatsapp/reference/whatsapp-business-phone-number/message-api
- Templates:
  https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/overview
- Service messages e janela de atendimento:
  https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/send-messages

Premissas confirmadas em 2026-06-18:

- Cloud API e a API oficial hospedada pela Meta para WhatsApp Business.
- O ambiente precisa de Meta Business Portfolio, WABA e business phone number.
- O envio usa `Phone-Number-ID` e endpoint `/messages`.
- Tokens exigem permissoes de WhatsApp Business Management/Messaging conforme
  caso de uso.
- Webhooks exigem endpoint verificavel e assinatura para payloads.
- Mensagens iniciadas pelo negocio dependem de template aprovado quando fora
  da janela de atendimento.

## Modos De Falha

Riscos tecnicos:

- Acoplar `/chat` a payload bruto Meta.
- Usar `wa_id` ou telefone bruto como `session_id` persistido.
- Tratar status Meta como decisao de handoff.
- Logar erro bruto da Meta com token, telefone ou payload.
- Criar dois caminhos paralelos de OTP com regras diferentes.
- Deixar Hermes virar contrato permanente por falta de data de remocao.
- Trocar n8n por Hermes sem reduzir acoplamento.

Mitigacoes:

- Adapter Meta normaliza payload antes de chamar o core.
- Persistencia continua usando hash chaveado.
- Handoff continua decidido pelo backend.
- Erros externos viram codigos sanitizados.
- `OtpDeliveryAdapter` continua sendo a unica porta de entrega de OTP.
- Feature flags documentadas e reversiveis.

## Rubrica De Avaliacao

A entrega futura so deve ser aceita se:

- O core RAG nao conhecer classes Meta, Hermes ou Evolution.
- `internal_webhooks.py` nao depender de `N8N_VERIFIED_*` (alias ja removido).
- Config generica `VERIFIED_*_WEBHOOK_URL` funcionar como unica fonte.
- Dispatcher separar evento interno de rota/provedor.
- Meta webhook validar token de verificacao e assinatura.
- Meta client enviar mensagem com timeout e erro sanitizado.
- OTP usar adapter e template, sem logar codigo puro.
- Testes cobrem assinatura invalida, replay, URL ausente, erro externo,
  payload invalido, status Meta e logs sem PII.
- Rollback para transporte anterior for possivel por env var.

## Validacao Esperada

Para fase apenas documental:

```powershell
git diff --check
```

Para fase de codigo:

```powershell
python -m compileall app tests scripts
python -m pytest
```

Testes esperados na fase de codigo:

- config generica `VERIFIED_*_WEBHOOK_URL`;
- ingress interno com evento desconhecido;
- ingress interno com HMAC invalido;
- dispatcher sem URL configurada;
- dispatcher com 4xx permanente;
- Meta webhook GET verification;
- Meta webhook POST com `X-Hub-Signature-256` invalida;
- parser de `messages` e `statuses`;
- Meta client com timeout;
- Meta client com erro sanitizado;
- `MetaWhatsAppOtpDeliveryAdapter` sem persistir/logar OTP puro;
- `MetaWhatsAppChatTransport` sem passar telefone bruto para persistencia.

## Ownership E Risco De Atropelo

Baixo risco para Renan:

- contratos;
- docs;
- interfaces;
- testes;
- adapters Python;
- seguranca e observabilidade.

Risco medio/alto com Juliano:

- secrets Meta;
- WABA, phone number, app subscription e webhooks reais;
- VPS, runtime, rede, TLS e logs;
- Hermes se for servico externo;
- retirada operacional de n8n/Evolution.

Regra pratica:

- Renan pode preparar contratos e codigo sem deploy real.
- Juliano precisa participar antes de ativar runtime, secrets, URL publica,
  phone number ou migracao operacional.

## Proximo Passo Seguro

Abrir uma branch pequena apenas para a Fase 1:

- adicionar settings genericos com alias legado;
- renomear mapas e logs sem mudar comportamento;
- atualizar contratos e observabilidade;
- adicionar testes de compatibilidade.

So depois disso criar a Fase 3 com Meta client/webhook.
