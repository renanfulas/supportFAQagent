# Conversation Archive Sink (seguro append-only contra perda)

Status: **implementado, default desligado** (`ENABLE_CONVERSATION_ARCHIVE=false`).
Destino durável escolhido: **object storage S3-compatible** (transporte `s3`).
Falta operacionalizar: criar bucket + credenciais e fazer o deploy do worker
`dispatch_outbox --loop` na VPS (ver "Deploy" abaixo).

## Por que existe

Postgres local é a fonte da verdade no hot path. O risco residual é perder
turnos já reconhecidos num restart/deploy/crash da VPS. Este sink é o "seguro":
uma cópia **append-only isolada**, fora da VPS, alimentada pelo outbox
transacional — sem tocar na latência da resposta.

Não é um segundo Postgres. É um log append-only (arquivo NDJSON hoje; log
gerenciado / fila / object store amanhã). Banco completo só se um dia quiserem
*consultar* o backup.

## Fluxo

```
record_chat (mesma transação do turno)
  ├─ grava chat_audits + conversations/messages   (fonte da verdade)
  └─ enfileira operational_outbox                  (cópia, mesma garantia ACID)
        event_type = 'conversation.turn.archived'
        idempotency_key = 'archive:{turn_id}'

dispatch_outbox (worker, fora do hot path)
  └─ transporte 'append_only_sink' → ConversationArchiveSink.append(...)
```

A escrita do turno e o enfileiramento da cópia commitam juntos: se a cópia não
foi enfileirada, o turno não foi reconhecido. O RPO é pequeno por construção
(fanout quase-real-time), sem escolher entre "perde minutos" e "perde zero".

## Contrato do sink

Interface estável em `app/conversations/archive_sink.py`:

```python
class ConversationArchiveSink(Protocol):
    def append(self, *, idempotency_key: str, event_type: str,
               request_id: str | None, payload: dict) -> None: ...
```

Garantias que qualquer implementação **deve** cumprir:

- **Append-only**: nunca reescreve nem trunca registros já gravados.
- **Durável na confirmação**: ao retornar de `append`, o registro sobrevive a um
  crash (a impl default faz `flush` + `fsync`).
- **Idempotência**: `idempotency_key` (`archive:{turn_id}`) permite deduplicar.
  O dispatcher pode reentregar (at-least-once); o destino deve tolerar repetição.
- **Sem PII crua**: `payload` já vem sanitizado (`sanitize_payload`,
  `redaction_version`). O sink não deve "des-sanitizar" nem logar o conteúdo.

Formato de cada registro (NDJSON, uma linha por turno):

```json
{"idempotency_key":"archive:<turn_id>","event_type":"conversation.turn.archived",
 "request_id":"<req>","payload":{...turno sanitizado...}}
```

## Configuração

| Var | Default | Papel |
| --- | --- | --- |
| `ENABLE_CONVERSATION_ARCHIVE` | `false` | Liga o enqueue da cópia (requer `PERSISTENCE_BACKEND=postgres`). |
| `OUTBOX_CONVERSATION_ARCHIVE_TRANSPORT` | `append_only_sink` | Transporte do dispatcher para o evento. `disabled` desliga a entrega. |
| `CONVERSATION_ARCHIVE_SINK_TRANSPORT` | `append_only_file` | Implementação concreta: `append_only_file` (stopgap local) ou `s3` (durável off-box). |
| `CONVERSATION_ARCHIVE_SINK_PATH` | — | Caminho do NDJSON (obrigatório para `append_only_file`). |
| `CONVERSATION_ARCHIVE_SINK_BUCKET` | — | Bucket (obrigatório para `s3`). |
| `CONVERSATION_ARCHIVE_SINK_PREFIX` | `conversations` | Prefixo de chave (`s3`). |
| `CONVERSATION_ARCHIVE_SINK_ENDPOINT_URL` | — | Endpoint S3-compatible (R2/B2/MinIO). Vazio = AWS S3. |
| `CONVERSATION_ARCHIVE_SINK_REGION` | — | Região AWS (`s3`), quando aplicável. |

Credenciais do `s3` vêm da cadeia padrão do boto3 (env `AWS_ACCESS_KEY_ID` /
`AWS_SECRET_ACCESS_KEY` ou role de instância), **nunca** deste módulo. Requer o
extra: `pip install '.[s3]'`.

## Destino S3-compatible (`s3`)

`S3ObjectSink` grava **um objeto imutável por turno** na chave determinística
`<prefix>/<shard>/<turn_ref>.json` (`shard` = 2 primeiros hex do `turn_ref`).
Como a chave é função pura do turno, uma reentrega do outbox sobrescreve o mesmo
objeto com bytes idênticos — idempotente sem condicional server-side, o que mantém
o adapter portátil entre AWS S3, Cloudflare R2, Backblaze B2 e MinIO (via
`endpoint_url`). Recomenda-se ligar **versionamento + Object Lock/WORM** no bucket
para reforçar o caráter append-only no nível da infra.

## Como trocar o destino (seam)

Para um novo destino (fila, log gerenciado, outro store), **sem** mudar chamadores
nem schema:

1. Implementar uma classe que satisfaça `ConversationArchiveSink`.
2. Adicionar o transporte em `SUPPORTED_SINK_TRANSPORTS` e o branch em
   `build_archive_sink_from_env`.

## Deploy (VPS)

O fanout só acontece com o worker rodando. Na VPS (ver topologia em runtime):

1. `.env`: `PERSISTENCE_BACKEND=postgres`, `ENABLE_CONVERSATION_ARCHIVE=true`,
   `CONVERSATION_ARCHIVE_SINK_TRANSPORT=s3`, bucket/região/credenciais.
2. Instalar o extra `s3` no `.venv` do serviço.
3. Rodar `python -m scripts.dispatch_outbox --loop` como serviço systemd dedicado
   (`Restart=always`), separado do `supportfaq.service`.

> Sync cirúrgico por arquivo em `/opt/supportFAQagent` (há drift não-commitado em
> prod); nunca `git reset --hard`/`git clean` lá.

## Validação

- Unit: `tests/test_conversation_archive_sink.py` (file sink, S3 sink, factory,
  roteamento e entrega do dispatcher).
- Integração gated (Postgres real, harness #84):
  `tests/integration/test_phase0_postgres.py::test_persisted_turn_is_fanned_out_to_append_only_sink`
  via `scripts/run_integration_tests.ps1`.
