# Plano Tecnico - Memoria de Sessao Pegajosa para Roteamento de Dominio

Status: seam implementado (contrato + adapter efimero + integracao no transporte
WhatsApp); storage duravel pendente da frente de persistencia.
Data de revisao: 2026-06-24.

## Problema

O `DomainRouter` (palavra-chave + menu) decide o dominio mensagem a mensagem e e
stateless. Sem memoria, uma conversa que ja escolheu `vendas` volta ao menu sempre
que manda uma mensagem generica sem palavra-chave (ex.: "pode explicar melhor?").
Isso quebra a fluidez de atender suporte E vendas no mesmo numero.

A correcao e lembrar o dominio escolhido por conversa: memoria de sessao pegajosa.

## Decisao de fronteira

- Orquestracao/contrato (Renan): define a interface, o adapter efimero em memoria, a
  logica de stickiness no transporte e os testes.
- Persistencia (Alexandre): implementa o adapter duravel (PostgreSQL) com a mesma
  interface, TTL e garantias de privacidade.

Assim ninguem atravessa a frente do outro: o transporte depende apenas do contrato.

## Contrato

`app/orchestration/session_domain_store.py`:

```python
class SessionDomainStore(Protocol):
    def get(self, session_id: str) -> str | None: ...
    def set(self, session_id: str, domain: str) -> None: ...
    def clear(self, session_id: str) -> None: ...
```

Regras do contrato:

- A chave e sempre o `session_id` ja sanitizado (hash, ex.: `whatsapp:meta:<digest>`).
  Nunca persistir `wa_id` cru, telefone ou texto da mensagem.
- `get` retorna `None` quando ausente ou expirado.
- `set` (re)vincula a sessao ao dominio e renova o TTL.
- `clear` esquece o vinculo (usado pelo gatilho de reset).
- TTL recomendado: janela curta de conversa (default efimero: 3600s). Ajustar com
  dados reais.

## Logica de stickiness (ja no transporte)

Em `MetaWhatsAppChatTransport._route_with_stickiness`:

1. Mensagem de reset (`menu`, `trocar`, `voltar`, `recomecar`, `inicio`, `opcoes`)
   -> `clear` + mostra menu.
2. Selecao explicita (`1`/`2`/nome) ou match de palavra-chave -> `set` e responde
   nesse dominio.
3. Mensagem generica (sem match) -> usa o dominio vinculado, se houver; senao mostra
   o menu.
4. Troca de dominio: uma palavra-chave forte do outro dominio re-vincula (passo 2).

A seguranca nao muda: o roteador so escolhe o dominio; handoff, confinamento e
politica continuam no `ChatFlowService` do dominio escolhido.

## Implementacao duravel (frente Alexandre)

1. Schema expand-only, ex.: `session_domain_binding(session_id_hash PK, domain,
   updated_at, expires_at)`. Sem PII; apenas hash de sessao e nome de dominio.
2. Adapter `PgSessionDomainStore(SessionDomainStore)` com upsert em `set`, leitura
   com checagem de `expires_at` em `get`, delete em `clear`.
3. Injetar o adapter no `MetaWhatsAppChatTransport(session_store=...)` no wiring de
   runtime, substituindo o `InMemorySessionDomainStore` (que nao sobrevive a
   restart nem e compartilhado entre workers).
4. Reusar o mesmo segredo/estrategia de hash de sessao ja usada no historico, para
   nao criar um segundo esquema de identidade. Ver
   `customer-identity-whatsapp-handoff-plan.md`.

## Validacao

- `tests/test_domain_router.py`: stickiness (follow-up generico mantem dominio),
  reset (limpa e mostra menu), TTL do store em memoria, chave = hash sanitizado.
- Quando o adapter duravel existir: teste opt-in com PostgreSQL validando
  persistencia entre instancias e expiracao por `expires_at`.

## Limites honestos

- O default em memoria e so para dev/single-process. Stickiness real em producao
  (multi-worker, pos-restart) depende do adapter duravel.
- Decisao continua por mensagem; nao ha NLU de intencao alem de palavra-chave/menu.
- Ativacao do canal Meta WhatsApp segue desligada por flag e fora deste plano.
