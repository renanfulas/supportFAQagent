# Runbook - Capacidade Da VPS E Limpeza Docker

## Objetivo

Manter a VPS operacional com alerta de disco, limpeza controlada de cache Docker
e protecao explicita dos volumes PostgreSQL/pgvector.

Este runbook e read-only por padrao. Limpeza exige decisao humana e evidencia
sanitizada antes e depois.

## Alertas De Disco

Thresholds operacionais:

- `75%`: warning; revisar crescimento de Docker, logs e banco.
- `85%`: critical; pausar mudancas, limpar cache seguro ou aumentar disco.
- menos de `2 GiB` livres: critical mesmo se o percentual ainda parecer menor.

Destino operacional aprovado para staging:

- WhatsApp via Hermes, rota `supportfaq-alerts`;
- acionar WhatsApp somente em `critical` por padrao;
- usar `warning` apenas como log/arquivo local, salvo decisao explicita de
  elevar ruido operacional.

Comando de capacidade:

```bash
python -m scripts.check_runtime_capacity --path / --warning 75 --critical 85 --min-free-gb 2
```

Para automacao simples via cron/systemd, tratar exit codes assim:

- `0`: ok
- `1`: warning
- `2`: critical

Exemplo de cron local, ajustando o destino privado do alerta:

```cron
*/15 * * * * cd /opt/supportFAQagent && .venv/bin/python -m scripts.check_runtime_capacity --path / --warning 75 --critical 85 --min-free-gb 2 --output /var/log/supportfaq-capacity.md || /usr/local/bin/supportfaq-disk-alert /var/log/supportfaq-capacity.md
```

O destino do alerta pode ser email, webhook interno ou painel do provedor, mas
nao deve publicar IP, hostname, usuario, portas administrativas ou secrets.

## Contrato Hermes `supportfaq-alerts`

Rota Hermes separada de OTP:

```yaml
supportfaq-alerts:
  events: []
  secret: <private>
  deliver: "whatsapp"
  deliver_only: true
  prompt: "{variables.message}"
  deliver_extra:
    chat_id: "{chat_id}"
```

Payload enviado pelo script:

```json
{
  "delivery_id": "supportfaq-capacity-...",
  "channel": "whatsapp",
  "phone_e164": "+5511937350535",
  "chat_id": "5511937350535@s.whatsapp.net",
  "template": "runtime_capacity_alert",
  "variables": {
    "message": "supportFAQ capacity alert: status=critical used_percent=86.2 free_gb=1.4 path=/ action=check_vps_capacity"
  }
}
```

Headers:

```http
X-Delivery-ID: <delivery-id>
X-Webhook-Timestamp: <unix-seconds>
X-Webhook-Signature: <hex-hmac-sha256-body>
```

Variaveis privadas recomendadas no runtime:

```bash
HERMES_ALERT_RECIPIENTS=+5511937350535,+554198060000
HERMES_ALERT_DELIVERY_PATH=/webhooks/supportfaq-alerts
HERMES_ALERT_WEBHOOK_SECRET=<private>
```

Se `HERMES_ALERT_WEBHOOK_SECRET` nao estiver definido, o script aceita
`HERMES_WEBHOOK_SECRET` como fallback para staging. Em producao, prefira segredo
dedicado por rota.

Comando de envio:

```bash
python -m scripts.send_runtime_capacity_alert \
  --path / \
  --warning 75 \
  --critical 85 \
  --min-free-gb 2 \
  --alert-on critical \
  --output /var/log/supportfaq-capacity-alert.md
```

Teste controlado:

```bash
python -m scripts.send_runtime_capacity_alert \
  --path / \
  --force-test \
  --output /var/log/supportfaq-capacity-alert-test.md
```

Mensagem permitida:

```text
supportFAQ capacity alert: status=critical used_percent=86.2 free_gb=1.4 path=/ action=check_vps_capacity
```

Dados proibidos no WhatsApp:

- IP, hostname, usuario ou porta administrativa;
- secrets, tokens, cookies ou `DATABASE_URL`;
- logs brutos, stack trace ou payload completo;
- nomes internos sensiveis alem do identificador operacional `supportFAQ`.

## Politica De Limpeza Docker

Limpeza permitida, apos registrar capacidade antes:

```bash
docker builder prune --filter "until=168h"
docker image prune --filter "dangling=true"
journalctl --vacuum-time=14d
```

Limpeza que exige janela operacional e revisao manual:

```bash
docker image ls
docker ps -a
docker system df
docker builder prune --all --filter "until=168h"
```

Comandos proibidos no host do `supportFAQagent` sem decisao explicita de
descomissionamento:

```bash
docker volume prune
docker system prune --volumes
docker rm -v <container>
```

Regra simples: build cache e imagem dangling sao poeira; volume PostgreSQL e o
caderno com os dados. Varra a poeira, nao jogue o caderno fora.

## Volumes PostgreSQL Protegidos

Antes de qualquer limpeza, listar volumes:

```bash
docker volume ls
docker ps -a --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
```

Tratar como protegido qualquer volume com nome contendo:

- `postgres`
- `postgresql`
- `pgdata`
- `pgvector`
- `supportfaq_db`

Tambem tratar como protegido qualquer volume anonimo montado por container
PostgreSQL/pgvector em `/var/lib/postgresql/data`, mesmo que o nome pareca um
hash sem significado.

Se houver duvida sobre um volume, nao remover. Confirmar primeiro qual container
usa o volume:

```bash
docker ps -a --filter volume=<volume-name>
```

## Restore Cronometrado Em VPS Isolada

O restore nao deve rodar sobre o staging oficial. O provedor precisa criar uma
VPS separada a partir do snapshot, sem DNS publico apontando para ela.

Evidencia minima:

- timestamp do snapshot;
- `restore_started_at`;
- `restore_finished_at`;
- confirmacao explicita de que o host validado e uma VPS restaurada isolada;
- `RTO = restore_finished_at - restore_started_at`;
- `RPO = horario do dado mais recente restaurado - timestamp do snapshot`;
- `python -m scripts.migrate verify`;
- `python -m scripts.check_readiness`;
- smoke HTTP sanitizado;
- validacao de pgvector, outbox e volumes.

Criterios:

- `RTO <= 4h`;
- `RPO <= 24h`;
- nenhum segredo ou dado sensivel em relatorio publico;
- staging oficial permanece intocado.

## Evidencia Sanitizada

Modelo curto:

```md
## Capacity

- generated_at: <iso8601>
- disk_status: ok|warning|critical
- used_percent: <n>
- free_gb: <n>
- docker_system_df: ok|warning|error
- postgres_volume_guard: present|unknown
- action: none|safe_cache_cleanup|disk_resize_required

## Restore

- snapshot_timestamp: <iso8601>
- restore_started_at: <iso8601>
- restore_finished_at: <iso8601>
- isolated_restored_vps: yes|no
- rto_minutes: <n>
- rpo_hours: <n>
- readiness: passed|failed
- pgvector_gate: passed|failed|not_run
- decision: approved|not_approved|blocked
```
