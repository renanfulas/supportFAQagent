# Especificacao V1 - Identidade De Canal Por WhatsApp OTP

## Objetivo

Definir o contrato tecnico da V1 para verificar que uma pessoa controla um
numero de WhatsApp e vincular essa identidade de canal a sessao web anonima da
V0.

Esta verificacao nao prova titularidade de conta HostGator. Ela prova apenas
posse temporaria do canal WhatsApp informado.

Documento pai:

- [Plano De Evolucao Do Chat Web](web-chat-evolution-plan.md)

## Decisoes Obrigatorias

- O browser continua sem receber `X-API-Key`, chaves de provider ou secrets.
- O telefone deve ser normalizado para E.164 antes de qualquer comparacao.
- Telefone bruto e codigo OTP nao devem aparecer em logs.
- Codigo OTP nao deve ser persistido em texto puro.
- Respostas publicas nao devem revelar se um telefone ja existe na base.
- o transporte externo do WhatsApp e adapter isolado; na direcao atual, Meta
  WhatsApp Cloud API e o caminho nativo e Hermes pode ser ponte temporaria.
- A identidade verificada e uma identidade de canal, nao uma conta HostGator.
- Persistencia, migrations e indices finais devem ser alinhados com Renan.

## Fora Do Escopo

- Vincular telefone a contrato ou conta HostGator.
- Historico omnichannel completo.
- Recuperacao de conta.
- Painel administrativo.
- Login por email ou senha.
- Regra de autenticacao implementada dentro de uma automacao externa.
- Liberar operacoes sensiveis apenas porque o telefone foi verificado.

## Fluxo

```text
Browser com cookie anonimo HttpOnly
  -> POST /web/auth/whatsapp/start
  -> backend normaliza telefone e cria desafio
  -> adapter de entrega solicita envio do OTP
  -> adapter externo envia mensagem pelo canal WhatsApp aprovado
  -> usuario informa codigo no website
  -> POST /web/auth/whatsapp/confirm
  -> backend valida digest, expiracao e tentativas
  -> sessao anonima passa a apontar para identidade de canal verificada
```

O backend decide validade, expiracao, tentativas e bloqueios. O workflow
externo apenas entrega a mensagem.

## Contratos HTTP Propostos

### `POST /web/auth/whatsapp/start`

Entrada:

```json
{
  "phone": "+5511999999999"
}
```

Regras:

- normalizar para E.164
- rejeitar campos extras
- aceitar apenas telefones validos para o escopo inicial do produto
- aplicar rate limit por IP e `phone_hash`
- invalidar ou substituir desafios pendentes anteriores conforme politica
- devolver resposta generica para reduzir enumeracao de usuarios

Resposta `202`:

```json
{
  "challenge_id": "uuid",
  "status": "pending",
  "expires_in_seconds": 300,
  "retry_after_seconds": 60
}
```

Erros publicos:

- `422 invalid_phone`
- `429 too_many_requests`
- `503 otp_delivery_unavailable`

### `POST /web/auth/whatsapp/confirm`

Entrada:

```json
{
  "challenge_id": "uuid",
  "code": "123456"
}
```

Regras:

- rejeitar campos extras
- aceitar apenas seis digitos no contrato inicial
- validar desafio, digest, expiracao, status e tentativas restantes
- consumir o desafio depois do sucesso
- bloquear desafio quando tentativas acabarem
- vincular a sessao web atual a identidade verificada
- nao devolver telefone bruto

Resposta `200`:

```json
{
  "status": "verified",
  "phone_last4": "9999"
}
```

Erro publico generico:

```json
{
  "detail": "invalid_or_expired_code"
}
```

Usar a mesma mensagem para codigo incorreto, desafio inexistente, consumido ou
expirado reduz vazamento de informacao.

### `GET /web/auth/session`

Objetivo:

- permitir que a UI descubra o estado atual sem expor PII

Resposta anonima:

```json
{
  "status": "anonymous"
}
```

Resposta verificada:

```json
{
  "status": "verified",
  "phone_last4": "9999"
}
```

### `POST /web/auth/logout`

Objetivo:

- remover o vinculo de identidade da sessao web atual
- preservar politica futura de retencao de conversas sem expor historico

Resposta:

```json
{
  "status": "anonymous"
}
```

## Persistencia Conceitual

O schema final pertence a frente de banco. O contrato da aplicacao precisa
destes conceitos:

```text
web_sessions
  id
  anonymous_session_hash
  verified_identity_id nullable
  created_at
  last_seen_at

verified_identities
  id
  channel
  phone_hash
  phone_last4
  verified_at
  status

otp_challenges
  id
  identity_candidate_hash
  code_digest
  expires_at
  attempts_remaining
  status
  created_at
  consumed_at nullable
```

Regras:

- nao persistir telefone bruto se o produto nao exigir recuperacao reversivel
- usar hash com chave privada para `phone_hash`, nao hash simples
- usar digest com segredo para OTP curto, porque seis digitos permitem brute
  force offline se o banco vazar
- separar identidade de canal de futura identidade de cliente HostGator

## Segredos E Configuracao

Variaveis propostas:

```dotenv
ENABLE_WEB_WHATSAPP_AUTH=false
OTP_CODE_TTL_SECONDS=300
OTP_RESEND_COOLDOWN_SECONDS=60
OTP_MAX_ATTEMPTS=5
OTP_START_LIMIT_PER_IP_PER_HOUR=10
OTP_START_LIMIT_PER_PHONE_PER_15_MINUTES=3
IDENTITY_HASH_SECRET=secret-privado
OTP_DIGEST_SECRET=secret-privado-diferente
```

Regras:

- secrets diferentes por ambiente
- nunca versionar valores reais
- nunca reutilizar `API_SECRET_KEY` como segredo de hash
- ativar a feature somente depois da persistencia e do transporte aprovados

## Fronteira Com Transporte WhatsApp

Contrato sugerido entre backend e adapter de entrega:

```json
{
  "delivery_id": "uuid",
  "channel": "whatsapp",
  "phone_e164": "+5511999999999",
  "template": "web_login_otp",
  "variables": {
    "code": "123456",
    "expires_in_minutes": 5
  }
}
```

Regras:

- este payload circula apenas em canal servidor-servidor protegido
- o adapter externo nao decide validade, expiracao ou tentativas
- logs do backend e do transporte nao devem registrar telefone ou codigo brutos
- quando o transporte for Meta, usar template aprovado e validar smoke privado
- quando o transporte for Hermes, tratar como ponte temporaria removivel

## Rate Limit Inicial

Baseline conservador:

| Acao | Limite inicial |
| --- | --- |
| iniciar desafio por IP | 10 por hora |
| iniciar desafio por telefone | 3 por 15 minutos |
| reenviar codigo | cooldown de 60 segundos |
| confirmar codigo | 5 tentativas por desafio |
| criar novo desafio apos bloqueio | cooldown progressivo |

Os valores devem ser configuraveis e ajustados com dados operacionais.

## Threat Model

| Risco | Controle minimo |
| --- | --- |
| enumeracao de telefone | respostas genericas |
| brute force de OTP | expiracao curta, tentativas limitadas e bloqueio |
| spam de mensagens | rate limit por IP e `phone_hash` |
| vazamento de banco | telefone com hash chaveado e OTP com digest secreto |
| vazamento em logs | mascarar telefone e nunca logar codigo |
| roubo de cookie | `HttpOnly`, `SameSite=Lax`, `Secure` fora de dev |
| confundir telefone com conta HostGator | copy e contrato explicitos |
| mover regra para automacao externa | backend continua dono da validacao |

## Observabilidade

Eventos propostos:

- `otp_challenge_requested`
- `otp_delivery_requested`
- `otp_delivery_failed`
- `otp_verification_succeeded`
- `otp_verification_failed`
- `otp_challenge_blocked`
- `web_session_logged_out`

Campos permitidos:

- `request_id`
- `challenge_id`
- `session_id_hash`
- `phone_hash`
- `phone_last4`
- `delivery_id`
- `status`
- `failure_code`

Campos proibidos:

- telefone bruto
- codigo OTP
- cookie
- payload completo do provider
- secrets

## Sequencia De Implementacao

### V1A - Contrato E Adapter

- alinhar schema com Renan
- definir adapter de entrega WhatsApp entre Renan e Juliano
- criar schemas HTTP e testes de validacao
- criar interface de storage para sessoes, identidades e desafios
- criar interface de entrega sem acoplar FastAPI a um provedor especifico

### V1B - Persistencia E Seguranca

- implementar migration aprovada
- implementar storage PostgreSQL
- implementar digest e geracao criptograficamente segura
- implementar rate limits e cooldown
- criar testes de expiracao, bloqueio e nao enumeracao

### V1C - Workflow E UI

- implementar workflow externo de entrega
- exportar JSON versionado do workflow
- adicionar tela de telefone e confirmacao no `ask-host-genius`
- validar logs sanitizados e smoke local

## Ownership

| Area | Responsavel primario |
| --- | --- |
| contratos HTTP, threat model e testes de seguranca | Renan |
| schema, migration, storage PostgreSQL e indices | Renan |
| transporte externo WhatsApp, secrets e conectividade | Juliano |
| runtime, secrets, HTTPS e logs do ambiente | Juliano |
| UI web para inicio e confirmacao do desafio | Renan |

## Gate Antes De Implementar

Responder com o time:

1. Qual transporte WhatsApp sera usado para entregar OTP?
2. O backend usa Meta nativa, Hermes temporario ou outro adapter direto?
3. O produto precisa recuperar telefone bruto ou apenas reconhecer o mesmo
   telefone por hash?
4. Conversa anonima continua disponivel depois que V1 entrar?
5. Qual ambiente executara o primeiro teste integrado sem exposicao publica?

## Validacao Esperada

Quando implementado:

```powershell
python -m compileall app tests scripts
python -m pytest
python -m app.evals.run_domain_eval suporte-vps-whatsapp
```

Testes obrigatorios:

- telefone invalido retorna `422`
- campos extras retornam `422`
- resposta de start nao enumera identidade existente
- codigo expira
- codigo nao pode ser reutilizado
- tentativas sao limitadas
- cooldown e rate limit retornam `429`
- logs nao contem telefone bruto nem OTP
- cookie continua `HttpOnly`
- `/chat` interno continua protegido
- V0 anonima continua funcionando conforme decisao de produto
