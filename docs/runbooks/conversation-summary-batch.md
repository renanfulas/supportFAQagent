# Runbook — Batch noturno de sumarização de conversa

Operação do `scripts/summarize_conversations.py` (persistência em camadas, Fase 3) e
do recall no RAG (Fase 4). Dark por default: nada roda nem custa até as flags serem
ligadas conscientemente. Ver `docs/quality-plans/conversation-persistence-tiering-plan.md`.

## Pré-requisitos (já satisfeitos na VPS)

- `PERSISTENCE_BACKEND=postgres`, migration `012_conversation_summaries` aplicada
  (`python -m scripts.migrate verify` lista 11+).
- `OPENAI_API_KEY` no `.env` (o sumarizador usa `gpt-4o-mini`).

## Flags (em `/opt/supportFAQagent/.env`)

| Flag | Papel | Default |
| --- | --- | --- |
| `ENABLE_CONVERSATION_SUMMARY` | permite o **batch escrever** resumos | off |
| `ENABLE_SUMMARY_RECALL` | injeta o resumo do cliente no prompt (`<untrusted_customer_history>`) | off |

Ligar uma **não** liga a outra. A ordem segura é: rodar o batch → **amostrar a
qualidade** → só então ligar o recall.

## 1. Dry-run (não chama o modelo, não escreve)

Conta quantas conversas estão elegíveis (inativas ≥ N horas, ≥ min turnos, ainda não
resumidas):

```bash
cd /opt/supportFAQagent
export DATABASE_URL="$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2-)"
.venv/bin/python -m scripts.summarize_conversations --dry-run --inactivity-hours 24 --min-turns 2
# -> {"event": "conversation_summary_dry_run", "eligible": N}
```

## 2. Rodada real bounded (amostragem)

Liga a flag e roda um lote pequeno para amostrar a qualidade antes de automatizar:

```bash
# liga só nesta sessão (não persiste no .env)
ENABLE_CONVERSATION_SUMMARY=true \
  DATABASE_URL="$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2-)" \
  .venv/bin/python -m scripts.summarize_conversations --inactivity-hours 24 --min-turns 2 --limit 5
# -> {"event": "conversation_summary_completed", "eligible": 5, "summarized": 5, "errors": 0}
```

Custo: ~US$0,0005/conversa (`gpt-4o-mini`). 5 conversas ≈ centavos.

## 3. Amostrar a qualidade (gate antes do recall)

Compare o resumo gerado com a conversa real (problema/solução/status):

```bash
.venv/bin/python - <<'PY'
import os, psycopg
durl=[l.split('=',1)[1].strip() for l in open('.env',encoding='utf-8',errors='replace') if l.startswith('DATABASE_URL=')][0]
with psycopg.connect(durl) as c, c.cursor() as cur:
    cur.execute("SELECT domain, status, problem, solution, source_turn_count, conversation_key FROM conversation_summaries ORDER BY summarized_at DESC LIMIT 10")
    for r in cur.fetchall(): print(r)
PY
```

Para cada amostra, abra a conversa original (`messages` por `conversation_id =
conversation_key`) e confira que problema/solução/status batem e **não há PII/PAN**.
Só ligue o recall quando a amostra estiver boa.

## 4. Automatizar (systemd timer, ~3h)

Units já criados na VPS (dormentes). Para ligar a automação:

```bash
# Persistir a flag de escrita
echo 'ENABLE_CONVERSATION_SUMMARY=true' >> /opt/supportFAQagent/.env  # se ainda não estiver
systemctl enable --now supportfaq-summarize.timer
systemctl list-timers supportfaq-summarize.timer   # confere o próximo disparo
journalctl -u supportfaq-summarize.service -n 20    # último resultado
```

### Conteúdo dos units (referência)

`/etc/systemd/system/supportfaq-summarize.service` (Type=oneshot):

```
[Service]
Type=oneshot
User=root
WorkingDirectory=/opt/supportFAQagent
EnvironmentFile=/opt/supportFAQagent/.env
ExecStart=/opt/supportFAQagent/.venv/bin/python -m scripts.summarize_conversations --inactivity-hours 24 --min-turns 2 --limit 500
```

`/etc/systemd/system/supportfaq-summarize.timer`:

```
[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
[Install]
WantedBy=timers.target
```

## 5. Ligar o recall (depois da amostragem)

```bash
echo 'ENABLE_SUMMARY_RECALL=true' >> /opt/supportFAQagent/.env
systemctl restart supportfaq.service
```

## Rollback

- Parar a automação: `systemctl disable --now supportfaq-summarize.timer`.
- Desligar a escrita: remover/`=false` `ENABLE_CONVERSATION_SUMMARY` (o batch volta a no-op).
- Desligar o recall: `ENABLE_SUMMARY_RECALL=false` + `systemctl restart supportfaq.service`.
- A tabela `conversation_summaries` é warehouse isolado; truncá-la não afeta o hot path.

## Notas

- O batch é **idempotente** (`UNIQUE(domain, conversation_key)`): re-rodar não duplica.
- Texto é **redigido (PAN/PII) antes** de ir ao modelo (`sanitize_for_persistence`).
- `customer_ref` = `customer_id` quando há identidade, senão `session_hash` — nunca
  telefone cru. Logs só com contagens (ver `docs/architecture/observability.md`).
