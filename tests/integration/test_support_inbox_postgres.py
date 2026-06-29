from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.db.runtime import DatabaseRuntime
from app.support.repository import SupportCaseRepository


DATABASE_URL = os.getenv("PHASE0_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set PHASE0_TEST_DATABASE_URL to run PostgreSQL integration tests",
)


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    if not DATABASE_URL:
        return
    env = {**os.environ, "DATABASE_URL": DATABASE_URL}
    result = subprocess.run(
        [sys.executable, "-m", "scripts.migrate", "apply"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, "migrations failed in disposable test database"


@pytest.fixture
def runtime() -> DatabaseRuntime:
    assert DATABASE_URL
    settings = SimpleNamespace(
        persistence_backend="postgres",
        web_auth_storage_backend="disabled",
        enable_outbox_ingress=False,
        session_domain_store_backend="memory",
        database_url=DATABASE_URL,
        database_pool_min_size=1,
        database_pool_max_size=4,
        database_connect_timeout_seconds=5,
        database_query_timeout_seconds=10,
        retrieval_backend="lexical",
    )
    database_runtime = DatabaseRuntime(settings)
    database_runtime.open()
    yield database_runtime
    database_runtime.close()


def test_list_cases_without_filters_executes_on_real_postgres(
    runtime: DatabaseRuntime,
) -> None:
    # Regression: the (%s IS NULL OR col = %s) filter sent a bare NULL parameter,
    # which real PostgreSQL rejects with IndeterminateDatatype ("could not
    # determine data type of parameter $1"). The FakeRuntime unit tests never
    # exercised type inference, so this only surfaced in production. The ::text
    # cast pins the type; this guards the no-filter list path against real PG.
    repository = SupportCaseRepository(runtime)
    rows = repository.list_cases(domain=None, status=None, limit=10, offset=0)
    assert isinstance(rows, list)


def test_list_cases_with_filters_executes_on_real_postgres(
    runtime: DatabaseRuntime,
) -> None:
    repository = SupportCaseRepository(runtime)
    rows = repository.list_cases(domain="vendas", status="open", limit=10, offset=0)
    assert isinstance(rows, list)
