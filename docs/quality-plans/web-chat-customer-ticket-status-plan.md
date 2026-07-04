# Plano De Produto - Status De Atendimento Para O Cliente (Web Chat)

Status: proposto em 2026-07-03. Nenhuma fase iniciada. Entrega incremental da
visao V3 do [web-chat-evolution-plan.md](web-chat-evolution-plan.md), do lado do
**cliente** (o console do time e o lado interno da mesma visao;
ver [support-team-console-plan.md](support-team-console-plan.md)).
Plano tecnico correspondente:
[web-chat-customer-ticket-status-tech-plan.md](web-chat-customer-ticket-status-tech-plan.md).

## Contexto E Problema

Hoje toda a maquina de handoff e team-facing. Quando o cliente do web chat
escala, autentica por OTP e consente (Sprint 4b do
[customer-identity-whatsapp-handoff-plan.md](customer-identity-whatsapp-handoff-plan.md)),
nasce um `support_case` duravel. O cliente recebe **uma** mensagem de
confirmacao com o codigo de suporte e depois disso: silencio.

Ele nao tem como responder "alguem esta olhando meu caso?", nem descobrir se o
atendimento foi assumido, resolvido ou se estao esperando uma resposta dele. O
time enxerga a fila inteira pelo console; o cliente enxerga nada. Falta o
espelho: uma visao autenticada de **"meus atendimentos"** para o cliente.

## Publico

Cliente final do **web chat** que ja abriu pelo menos um `support_case` (ou seja,
ja passou por OTP + consentimento). Nao e superficie de time, nao e para
anonimos.

## Onde Isto Se Encaixa

- E a metade cliente da V3 do `web-chat-evolution-plan.md`. O
  `support-team-console-plan.md` cobriu a metade time (fila, semaforo, metricas).
- Nao depende da V2 omnichannel completa (que foi descopada de proposito): roda
  inteiramente sobre dados ja persistidos em `support_cases`.
- **Escopo de canal, explicito:** so o cliente **web-verificado**. O WhatsApp
  nativo (Hermes/Meta) e canal propositalmente separado — la o time responde na
  propria thread que o cliente iniciou, entao "status de ticket" nao se aplica.
  Nao tentar unificar os dois canais.

## Principios De Produto

Alinhados a [product-positioning.md](../product-positioning.md):

1. **Honesto, nao magico.** Mostrar estado real e datas reais. Nunca prometer
   prazo que o produto nao garante (sem SLA contratual ao cliente).
2. **O cliente ve o dele, so o dele.** Autorizacao por `customer_id` resolvido no
   backend, jamais por parametro do browser.
3. **"Sanitizado para o time" nao e "seguro para o cliente".** O
   `context_snapshot_sanitized` foi sanitizado para o **operador** (reason codes
   internos, referencias de KB, confianca). O cliente recebe uma **projecao
   propria**, mais estreita.
4. **Privacidade preservada.** Sem telefone bruto, sem PII em log, sem enumeracao
   de tickets para sessao nao verificada.

## O Que Ja Existe E Sera Reaproveitado

O trabalho pesado (identidade, ticket duravel, sanitizacao) ja esta feito:

- **Auth de cliente:** `/web/auth/whatsapp/start|confirm|session`,
  `verified_identities`, `web_sessions`, e o `CurrentIdentityResolver`
  (`app/identity/current.py`) que traduz sessao web -> `customer_id`.
- **Ticket duravel:** `support_cases` com `status`, `opened_at`, `updated_at`,
  `closed_at`, `customer_id`, `request_id` (o proprio codigo de suporte que o
  cliente ja recebeu no `/web/chat`).
- **Transicoes auditadas** (Fase B do console): `open`, `in_progress`,
  `waiting_customer`, `closed`, `cancelled`, com eventos.
- **Filtro de `pending_consent`** ja existe no inbox interno (nunca vaza casos
  pre-consentimento sem filtro explicito) — mesma disciplina se aplica aqui.

Ou seja: a parte dificil (autenticar o cliente) esta pronta. Para mostrar os
tickets, resolvemos `customer_id` da sessao verificada atual e lemos
`support_cases WHERE customer_id = :resolved`.

## Decisoes De Design E Tensoes Criticas

Os pontos abaixo sao o que faz esta frente dar certo ou vazar. Fechar antes de
codar.

### 1. Superficie separada da do staff (colisao de rota)

O console do time ocupa `/web/support/*` com auth de staff dedicada
(`staff_members`/`staff_sessions`, cookie `Path=/web/support`, dark por
`ENABLE_SUPPORT_CONSOLE`). O cliente **nao** pode cair ai. Superficie proposta:
`/web/tickets/*`, com a **auth de cliente** (cookie de sessao web publica +
`verified_identity`), atras de uma flag propria
`ENABLE_WEB_CUSTOMER_TICKETS` (dark por padrao, `404` em toda a superficie
quando desligada, inclusive para nao revelar a feature).

### 2. Projecao segura para o cliente (o que ele ve e o que ele nao ve)

| Campo interno | Cliente ve? |
| --- | --- |
| `request_id` (codigo de suporte) | Sim — e o `ticket_code`, ele ja tem |
| `status` | Sim, **traduzido** (ver item 3) |
| `opened_at`, `updated_at`, `closed_at` | Sim, como datas amigaveis |
| pergunta de abertura do proprio cliente | Sim (texto que ele mesmo escreveu) como assunto |
| dominio | Sim, como rotulo amigavel |
| `reason_codes` internos | **Nao** |
| confianca / `confidence` | **Nao** |
| referencias de KB usadas | **Nao** |
| `priority` / semaforo / prazo SLA | **Nao** (constructo interno; "low" assustaria) |
| nome do operador dono do caso | **Nao** (no maximo "um atendente") |
| `context_snapshot_sanitized` (bloco do time) | **Nao** |

O assunto seguro e a **propria pergunta de abertura do cliente** (ele escreveu,
pode receber de volta) e/ou um rotulo neutro por dominio. Nao reaproveitar o
resumo do time como assunto.

### 3. Traducao de vocabulario de status + esconder `pending_consent`

Mapa cliente-facing (calibravel na copy):

| Status interno | Rotulo ao cliente |
| --- | --- |
| `open` | "Recebido, na fila" |
| `in_progress` | "Em analise por um atendente" |
| `waiting_customer` | "Aguardando sua resposta" |
| `closed` | "Resolvido" |
| `cancelled` | "Encerrado" |
| `pending_consent` | **nunca aparece** (nao e ticket ainda; mostrar confundiria e vazaria um caso meio-criado) |

`waiting_customer` e o mais util de expor: diz ao cliente que a bola esta com
ele — e o gancho natural para a Fase B.

### 4. Sessao efemera vs ticket duravel (re-autenticacao)

O OTP vincula `verified_identity` a **sessao atual** (cookie). Sessao e efemera
(cookie limpo, troca de aparelho). Um cliente que abriu ticket ontem no celular
e volta hoje no desktop pode nao estar mais "verificado" naquela sessao, embora
a `verified_identity` persista.

Decisao: para ver os tickets, o cliente **re-autentica por OTP** (o mesmo fluxo
que ele ja conhece). Barato, seguro e consistente com o consent gate. A UI deve
deixar isso claro ("confirme seu WhatsApp para ver seus atendimentos") em vez de
mostrar lista vazia e parecer que os tickets sumiram. Limitacao aceita e
documentada.

### 5. Nao-enumeracao

`GET /web/tickets` de sessao **nao verificada** responde
`{ "status": "anonymous", "tickets": [] }` — nunca "voce tem 0 tickets para o
telefone X". `GET /web/tickets/{code}` de caso que nao pertence ao
`customer_id` autenticado responde `404` (nao `403`, para nao confirmar
existencia). Mesma disciplina anti-enumeracao do OTP.

### 6. Read-only primeiro; acao e notificacao depois

O corte seguro do MVP e **somente leitura de status**. Responder em
`waiting_customer` (write) e notificar o cliente a cada mudanca de status
(outbound) sao fases seguintes, com suas proprias garantias.

## Contratos HTTP Propostos

### `GET /web/tickets`

- Auth: cookie de sessao web verificada (via OTP). Anonima -> `200` com
  `{ "status": "anonymous", "tickets": [] }`.
- Resolve `customer_id` **no backend**; o browser nunca envia `customer_id` nem
  telefone.
- Exclui `pending_consent`. Paginacao simples.

Resposta verificada:

```json
{
  "status": "verified",
  "tickets": [
    {
      "ticket_code": "uuid-do-request_id",
      "status": "in_progress",
      "status_label": "Em analise por um atendente",
      "subject": "Nao consigo acessar o painel apos migracao",
      "domain_label": "Suporte VPS e WhatsApp",
      "opened_at": "2026-07-03T12:00:00Z",
      "last_update_at": "2026-07-03T13:10:00Z"
    }
  ]
}
```

### `GET /web/tickets/{ticket_code}`

- `ticket_code` = o codigo de suporte que o cliente ja tem (`request_id`).
- Resolve o caso por `request_id AND customer_id = :resolved`. Nao pertence ao
  cliente autenticado -> `404`.
- Detalhe cliente-safe: status, datas, assunto, e (opcional) uma linha do tempo
  projetada ("Recebido em X" -> "Um atendente assumiu em Y" -> "Resolvido em Z",
  sem identidade de operador). Fecha com copy de reforco ("um atendente vai te
  responder pelo contato que voce autorizou").

## Fases E Criterios De Aceite

### Fase A - Leitura de status (read-only)

Entregas: `GET /web/tickets` + `GET /web/tickets/{code}`, projecao cliente-safe,
flag `ENABLE_WEB_CUSTOMER_TICKETS` dark por padrao, UI "meus atendimentos" no
web chat (`ask-host-genius`).

Criterios de aceite:

- Cliente verificado ve **somente** seus proprios casos.
- `pending_consent` nunca aparece.
- Sessao anonima nao enumera (lista vazia + convite a confirmar WhatsApp).
- Cliente A nao acessa caso do cliente B (`404`).
- Nenhum segredo, PII bruta, reason code interno, nome de operador ou referencia
  de KB no browser.
- `/web/support` (staff) e `GET /support`/`/internal/support-cases` (integracoes)
  intocados.
- Readiness alerta combinacao invalida (feature ligada sem
  `ENABLE_WEB_WHATSAPP_AUTH` ou sem `PERSISTENCE_BACKEND=postgres`).

### Fase B - Responder em `waiting_customer`

Quando o caso esta `waiting_customer`, o cliente pode enviar uma resposta que
vira mensagem sanitizada no caso e devolve o status para `in_progress`,
gerando evento auditado e notificando o time. Fecha o loop hoje morto (o time
espera, mas o cliente nao tem canal de volta sem abrir chat novo).

Criterios: write idempotente, rate limit, sanitizacao, evento auditado, so o
dono `customer_id` escreve no proprio caso.

### Fase C - Notificacao de mudanca de status ao cliente

Quando o time muda status (assumiu / resolveu), enfileira mensagem sanitizada ao
cliente pelo canal WhatsApp **ja consentido**, reaproveitando outbox +
`whatsapp.message.requested`.

Criterios: dentro do escopo do consentimento LGPD ja dado ("contato direto da
equipe"), com **opt-out**, idempotente por caso+transicao, sem PII alem do
autorizado, falha de envio nao corrompe o caso.

## Nao-Objetivos

- Nao virar portal/helpdesk completo (sem anexos, sem chat ao vivo embutido no
  painel no MVP).
- Nao unificar com WhatsApp nativo (canal separado; la se responde na thread).
- Nao expor reason codes internos, confianca, referencias de KB, prioridade/SLA
  interno ou nome do operador.
- Nao criar identidade nova: reaproveita `verified_identity`/`customer_id`.
- Nao mover autorizacao para o frontend: quem resolve `customer_id` e o backend.

## Riscos

- **Vazamento cross-customer** (o pior). Mitigacao: resolver sempre por
  `customer_id` da sessao, `404` em caso alheio, teste explicito A != B.
- **Reusar sanitizacao do time como se fosse do cliente.** Mitigacao: projecao
  propria + teste de campos proibidos no payload cliente.
- **Mostrar `pending_consent`.** Mitigacao: filtro explicito + teste.
- **Sessao efemera confundir ("sumiram meus tickets").** Mitigacao: copy clara +
  re-OTP; limitacao documentada.
- **Fase C virar spam / reabrir ferida.** Mitigacao: opt-out, idempotencia,
  dentro do consentimento.

## Ownership

- Contratos, backend, autorizacao, testes e docs: Renan.
- UI (repo `ask-host-genius`, area do cliente no web chat): Renan, stack ja em
  producao no chat publico.
- Deploy/VPS/Nginx do frontend: Juliano.

## Validacao

- `python -m compileall app tests scripts`
- `python -m pytest` (novo `tests/test_web_customer_tickets.py`: autorizacao
  A != B, nao-enumeracao anonima, `pending_consent` oculto, projecao sem campos
  proibidos, `404` em caso alheio)
- Revisao de privacidade do payload cliente e dos logs novos.
- Checks de readiness para combinacao Auth + persistencia + feature ligada.
- Contrato novo documentado em
  [`../architecture/integration-contracts.md`](../architecture/integration-contracts.md)
  quando a Fase A entrar em codigo.
