# Runbook - PostgreSQL Pgvector Local Em WSL1

## Objetivo

Executar migrations e gates PostgreSQL reais em um host Windows sem
virtualizacao habilitada e sem tocar no PostgreSQL nativo ou em staging.

WSL1 compartilha a rede do Windows. Use uma porta exclusiva e credenciais
somente de laboratorio.

## Preparacao

Em PowerShell:

```powershell
wsl --set-default-version 1
wsl --install -d Ubuntu --no-launch
wsl -d Ubuntu -u root -- apt-get update
wsl -d Ubuntu -u root -- apt-get install -y postgresql postgresql-contrib postgresql-18-pgvector
```

Configure uma porta livre, por exemplo `55432`, no
`/etc/postgresql/18/main/postgresql.conf`, e inicie:

```powershell
wsl -d Ubuntu -u root -- pg_ctlcluster 18 main start
wsl -d Ubuntu -u root -- pg_isready -p 55432
```

Crie role, banco e extensao usando valores privados de laboratorio. Nunca
reutilize credenciais de staging.

Se a role usada pela aplicacao nao for superusuaria, uma role administrativa
deve provisionar `vector` e `pgcrypto` no banco antes do runner. A migration
`001` usa `CREATE EXTENSION IF NOT EXISTS`, mas PostgreSQL nao permite que uma
role comum instale extensoes ainda ausentes.

## Gates

Defina `DATABASE_URL`, `PHASE0_TEST_DATABASE_URL`, `PERSISTENCE_HASH_SECRET` e
`PERSISTENCE_HASH_VERSION` somente na sessao atual.

Em banco novo:

```powershell
python -m scripts.migrate status
python -m scripts.migrate apply --target 006_conversations_messages.sql
python -m scripts.backfill_conversation_privacy --verify-contract-ready --quiet-period-seconds 0
python -m scripts.migrate apply
python -m scripts.migrate apply
python -m scripts.migrate verify
python -m pytest tests/integration/test_phase0_postgres.py tests/integration/test_conversation_migration_upgrade.py tests/integration/test_feedback_privacy_integrity_postgres.py -q
python -m pytest -q
```

## Restart

```powershell
wsl -d Ubuntu -u root -- pg_ctlcluster 18 main restart
python -m scripts.migrate verify
```

## Limites

- esse banco e descartavel e nao substitui staging;
- WSL1 nao permite validar Docker, rede privada de containers ou volumes;
- snapshot e restore do provedor continuam obrigatorios;
- nunca aponte `PHASE0_TEST_DATABASE_URL` para banco compartilhado ou oficial.
