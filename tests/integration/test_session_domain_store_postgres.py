from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.db.runtime import DatabaseRuntime
from app.orchestration.session_domain_store import PgSessionDomainStore


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
        session_domain_store_backend="postgres",
        database_url=DATABASE_URL,
        database_pool_min_size=1,
        database_pool_max_size=4,
        database_connect_timeout_seconds=5,
        database_query_timeout_seconds=10,
        retrieval_backend="lexical",
    )
    database_runtime = DatabaseRuntime(settings)
    database_runtime.open()
    with database_runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE session_domain_binding")
    yield database_runtime
    database_runtime.close()


def test_set_then_get_returns_domain(runtime: DatabaseRuntime) -> None:
    store = PgSessionDomainStore(runtime)
    store.set("whatsapp:hermes:abc", "vendas")
    assert store.get("whatsapp:hermes:abc") == "vendas"


def test_set_is_idempotent_upsert(runtime: DatabaseRuntime) -> None:
    store = PgSessionDomainStore(runtime)
    store.set("whatsapp:hermes:abc", "vendas")
    store.set("whatsapp:hermes:abc", "suporte-vps-whatsapp")
    assert store.get("whatsapp:hermes:abc") == "suporte-vps-whatsapp"
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM session_domain_binding")
            assert cursor.fetchone()[0] == 1


def test_clear_forgets_binding(runtime: DatabaseRuntime) -> None:
    store = PgSessionDomainStore(runtime)
    store.set("whatsapp:hermes:abc", "vendas")
    store.clear("whatsapp:hermes:abc")
    assert store.get("whatsapp:hermes:abc") is None


def test_expired_binding_is_not_returned(runtime: DatabaseRuntime) -> None:
    store = PgSessionDomainStore(runtime)
    store.set("whatsapp:hermes:abc", "vendas")
    # Force the binding into the past instead of sleeping.
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE session_domain_binding SET expires_at = now() - interval '1 minute' "
                "WHERE session_id_hash = %s",
                ("whatsapp:hermes:abc",),
            )
    assert store.get("whatsapp:hermes:abc") is None


def test_never_expires_when_ttl_zero(runtime: DatabaseRuntime) -> None:
    store = PgSessionDomainStore(runtime, ttl_seconds=0)
    store.set("whatsapp:hermes:abc", "vendas")
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT expires_at FROM session_domain_binding WHERE session_id_hash = %s",
                ("whatsapp:hermes:abc",),
            )
            assert cursor.fetchone()[0] is None
    assert store.get("whatsapp:hermes:abc") == "vendas"
