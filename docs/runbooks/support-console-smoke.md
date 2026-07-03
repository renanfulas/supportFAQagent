# Runbook - Smoke do console de suporte (Fase A)

Roteiro de validacao da fachada staff `/web/support/*` em staging antes de
promover a producao. Plano tecnico:
[support-team-console-tech-plan.md](../quality-plans/support-team-console-tech-plan.md).

## Pre-requisitos

1. Migration `014_support_console_staff.sql` aplicada pelo fluxo padrao de
   deploy (`python scripts/migrate.py`).
2. `PERSISTENCE_BACKEND=postgres` ativo e entrega de OTP configurada
   (`WEB_AUTH_OTP_DELIVERY_TRANSPORT=hermes` ou `meta`).
3. Operadores cadastrados:

```bash
python scripts/manage_staff.py add "+55XXXXXXXXXXX" --name "Renan"
python scripts/manage_staff.py list
```

4. `ENABLE_SUPPORT_CONSOLE=true` no ambiente e servico reiniciado.
5. `GET /health/ready` com o componente `support_console` em `ok` (ele acusa
   persistencia ausente, tabelas staff faltando ou entrega nao configurada).

## Smoke pela API

Executar na origem do backend (ou via proxy `/web/*`), guardando os
`request_id` das respostas:

1. **Dark por padrao** (antes de ligar a flag): `GET /web/support/auth/session`
   responde `404`.
2. **Login OTP real**: `POST /web/support/auth/start` com o proprio telefone →
   `202`; codigo chega no WhatsApp; `POST /web/support/auth/confirm` com os 6
   digitos → `200` com `display_name` e cookies `sfa_staff_session` +
   `sfa_staff_hint`.
3. **Sessao**: `GET /web/support/auth/session` → `200 authenticated: true`,
   `expires_at` na proxima 4h no fuso do time.
4. **Fila com semaforo**: `GET /web/support/cases` → `200`; conferir bloco
   `sla` (cor, explicacao em pt-BR), ordenacao attention e `truncated: false`.
5. **Detalhe de caso**: `GET /web/support/cases/{case_id}` de um ticket real →
   transcript sanitizado, referencias e bloco `sla`.
6. **Telefone nao-staff negado**: `POST /web/support/auth/start` com numero
   fora da tabela → mesmo `202`; `confirm` com qualquer codigo → `400
   invalid_or_expired_code`; nenhum OTP entregue.
7. **Logout**: `POST /web/support/auth/logout` → sessao morre
   (`GET /web/support/auth/session` → `401` com `hint` preservado);
   novo start sem telefone (1 clique) dispara OTP; com
   `{"forget_device": true}` o `hint` some.
8. **Logs**: conferir `support_console_auth_started/confirmed` sem telefone,
   codigo ou token — apenas hash truncado e `staff_id`.

## Smoke pela UI (`/team` no ask-host-genius)

Apos o deploy da tela por Juliano (mesmo fluxo do `deploy_ask_host_genius`),
repetir os passos 2-7 pela interface: login com codigo de 6 celulas, botao
"Entrar como <nome>" no segundo acesso, fila com semaforo e filtros, detalhe,
"entrar com outro numero" e "esquecer este dispositivo".

## Promocao a producao

Repetir a sequencia inteira em producao (migration → cadastro → flag → smoke
API → smoke UI). Rollback: `ENABLE_SUPPORT_CONSOLE=false` devolve `404` em
toda a superficie sem tocar dados; o inbox interno com `X-API-Key`
(`GET /internal/support-cases`) segue como break-glass.

## Incidentes conhecidos

- **OTP nao chega**: a resposta continua `202` de proposito (anti-side-channel);
  procurar `support_console_auth_delivery_failed` nos logs e validar o
  transporte (Hermes/Meta). Break-glass via inbox interno.
- **Rotacao de `IDENTITY_HASH_SECRET`**: invalida os `phone_hash` de
  `staff_members`; rodar `manage_staff.py add` de novo para cada operador.
