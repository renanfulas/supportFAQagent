# Runbook — Redis para o estado quente de sessão (Nível 1)

Operação do `RedisSessionStateStore` (persistência em camadas, Fase 2 / Nível 1).
Dá durabilidade ao **estado quente** de sessão (sobrevive a restart do app e é
consistente entre workers uvicorn). **Não-autoritativo**: a verdade é o Postgres
write-through; tudo é **fail-open** (Redis fora ⇒ "sem estado", nunca derruba o
`/chat`). Ver `docs/quality-plans/conversation-persistence-tiering-tech-plan.md` §Fase 2.

## Quando ligar (gatilho)

Só quando o estado de sessão precisar sobreviver a restart / multi-worker. Em
single-process o `InMemorySessionStateStore` (default) basta. **Não** torne o Redis
âncora de durabilidade (regra de ouro do plano de decisão).

## 1. Instalar e configurar o Redis na VPS

```bash
apt-get install -y redis-server   # ou container
```

Em `/etc/redis/redis.conf` (dado crítico operacional, não cache descartável):

```
appendonly yes
appendfsync everysec          # perde <= 1s no crash do processo
maxmemory 256mb
maxmemory-policy volatile-ttl # despeja SÓ chaves com TTL; nunca dado sem TTL
bind 127.0.0.1                # loopback (ou rede interna)
requirepass <senha-forte>
```

```bash
systemctl enable --now redis-server
redis-cli -a <senha> ping   # PONG
```

Backup do AOF e restore testados (é estado operacional, não descartável).

## 2. Instalar o extra e ligar a flag

```bash
cd /opt/supportFAQagent
.venv/bin/pip install -e '.[redis]'
```

No `.env`:

```
SESSION_STATE_BACKEND=redis
SESSION_STATE_REDIS_URL=redis://:<senha>@127.0.0.1:6379/0
# SESSION_STATE_TTL_SECONDS=2700   # 45 min (default)
```

`systemctl restart supportfaq.service` e confirmar `/health` 200. (O app **recusa
subir** com `SESSION_STATE_BACKEND=redis` sem `SESSION_STATE_REDIS_URL` — validação
de config, fail-fast.)

## 3. Verificar

```bash
# chaves do estado quente (nunca session_id cru — só hash)
redis-cli -a <senha> --scan --pattern 'sess:*' | head
```

- Com Redis **up**: o estado sobrevive a `systemctl restart supportfaq.service`
  dentro do TTL.
- Com Redis **down** (`systemctl stop redis-server`): o `/chat` responde normal
  (fail-open); a escrita/leitura de estado vira no-op até o Redis voltar.

## Rollback

```
SESSION_STATE_BACKEND=memory   # (ou remover a linha)
```
`systemctl restart supportfaq.service`. Volta ao store in-memory; nada quebra (o
estado é não-autoritativo).

## Notas

- Chave: `sess:{domain}:{channel}:{session_hash}` — só o hash já sanitizado, nunca
  telefone/`session_id` cru. Valor = JSON sanitizado de `SessionState`.
- `volatile-ttl` é obrigatório: a eviction **não** pode descartar dado sem TTL.
- O readiness (`/health/ready`) não pinga o Redis hoje (não-fatal para liveness);
  monitore o Redis pela operação padrão (systemd + `redis-cli ping`).
