# Runbook - Harness local de PostgreSQL para testes de integracao

## Objetivo

Executar localmente a suite de integracao PostgreSQL que normalmente so roda na
CI, usando um banco descartavel com pgvector. Sem configuracao, esses testes
fazem `skip` de proposito.

Testes cobertos (gated por `PHASE0_TEST_DATABASE_URL`):

- `tests/integration/test_phase0_postgres.py`
- `tests/integration/test_feedback_privacy_integrity_postgres.py`
- `tests/integration/test_conversation_migration_upgrade.py`

Este runbook nao altera o mecanismo de skip. Ele apenas fornece um banco
descartavel e as variaveis de ambiente esperadas para que os testes rodem.

## Como o skip funciona

Cada arquivo gated le `PHASE0_TEST_DATABASE_URL` no import:

```python
DATABASE_URL = os.getenv("PHASE0_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set PHASE0_TEST_DATABASE_URL to run PostgreSQL integration tests",
)
```

Alem disso, `tests/integration/conftest.py` recusa rodar contra qualquer banco
que nao seja claramente descartavel:

- exige `PHASE0_TEST_DATABASE_DISPOSABLE=true`;
- exige que o nome do banco contenha `test`, `phase0` ou `disposable`.

O harness deste runbook respeita as duas guardas.

## Pre-requisitos

- Docker e `docker compose` disponiveis.
- Dependencias instaladas: `pip install -e ".[dev]"`.

## Banco descartavel

O arquivo `docker-compose.test.yml` na raiz sobe `pgvector/pgvector:pg16` com o
banco `supportfaq_phase0`, espelhando a imagem e o nome usados pela CI
(`.github/workflows/phase0-gates.yml`). Ele e descartavel por design:

- senha literal somente de laboratorio (nunca reutilize segredo de staging/prod);
- dados em `tmpfs`, descartados quando o container e removido;
- porta de host `55432` para nao colidir com um PostgreSQL nativo em `5432`.

## Fluxo recomendado (script)

Linux / Git Bash:

```bash
./scripts/run_integration_tests.sh
```

Windows PowerShell:

```powershell
./scripts/run_integration_tests.ps1
```

O script faz todo o ciclo:

1. sobe o Postgres descartavel e aguarda ficar `healthy`;
2. exporta `PHASE0_TEST_DATABASE_URL`, `PHASE0_TEST_DATABASE_DISPOSABLE`,
   `DATABASE_URL`, `PERSISTENCE_HASH_SECRET` e `PERSISTENCE_HASH_VERSION`;
3. roda `python -m scripts.migrate apply`;
4. roda `python -m pytest tests/integration`;
5. derruba o banco com `docker compose ... down -v`.

Para manter o banco rodando apos a suite (debug):

```bash
KEEP_DB=1 ./scripts/run_integration_tests.sh
```

```powershell
./scripts/run_integration_tests.ps1 -KeepDb
```

## Fluxo manual (one-liner equivalente)

Se preferir controlar cada passo:

```bash
docker compose -f docker-compose.test.yml up -d

export PHASE0_TEST_DATABASE_URL="postgresql://postgres:throwaway_test_password@127.0.0.1:55432/supportfaq_phase0"
export PHASE0_TEST_DATABASE_DISPOSABLE="true"
export DATABASE_URL="$PHASE0_TEST_DATABASE_URL"
export PERSISTENCE_HASH_SECRET="local-phase0-test-secret"
export PERSISTENCE_HASH_VERSION="hmac-sha256-v1"

python -m scripts.migrate apply
python -m pytest tests/integration -q

docker compose -f docker-compose.test.yml down -v
```

## Verificacao do skip

Sem `PHASE0_TEST_DATABASE_URL`, os testes devem aparecer como `skipped` e a suite
normal continua verde:

```bash
python -m pytest tests/integration -q
```

## Validacao geral

```bash
python -m compileall app tests scripts
python -m pytest
```

## Notas de seguranca

- A senha do compose e descartavel e somente de laboratorio. Nao copie segredo de
  staging ou producao para este harness.
- O banco nao tem volume persistente; ao derrubar o container os dados somem.
- Este fluxo e complementar ao runbook `local-wsl1-pgvector-phase0.md` (host sem
  Docker/virtualizacao). Use Docker quando disponivel; WSL1 como alternativa.
```
