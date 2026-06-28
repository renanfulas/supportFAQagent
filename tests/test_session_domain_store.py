from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.core.errors import DatabaseUnavailableError
from app.orchestration.session_domain_store import (
    InMemorySessionDomainStore,
    PgSessionDomainStore,
    build_session_domain_store,
)


class _FakeCursor:
    def __init__(self, calls: list, fetch):
        self._calls = calls
        self._fetch = fetch

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def execute(self, sql: str, params=None) -> None:
        self._calls.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self._fetch


class _FakeConnection:
    def __init__(self, calls: list, fetch):
        self._calls = calls
        self._fetch = fetch

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._calls, self._fetch)


class _FakeRuntime:
    """Minimal DatabaseRuntime stand-in: records SQL or raises on transaction."""

    def __init__(self, *, persistence_enabled=True, fetch=None, raise_unavailable=False, backend="postgres"):
        self.persistence_enabled = persistence_enabled
        self._fetch = fetch
        self._raise = raise_unavailable
        self.calls: list = []
        self.settings = SimpleNamespace(session_domain_store_backend=backend)

    @contextmanager
    def transaction(self):
        if self._raise:
            raise DatabaseUnavailableError("boom")
        yield _FakeConnection(self.calls, self._fetch)


# --- factory routing -------------------------------------------------------

def test_build_returns_in_memory_by_default():
    runtime = _FakeRuntime(backend="memory")
    store = build_session_domain_store(runtime)
    assert isinstance(store, InMemorySessionDomainStore)


def test_build_returns_postgres_when_enabled():
    runtime = _FakeRuntime(backend="postgres", persistence_enabled=True)
    store = build_session_domain_store(runtime)
    assert isinstance(store, PgSessionDomainStore)


def test_build_falls_back_to_memory_when_persistence_off():
    runtime = _FakeRuntime(backend="postgres", persistence_enabled=False)
    store = build_session_domain_store(runtime)
    assert isinstance(store, InMemorySessionDomainStore)


# --- PgSessionDomainStore SQL shape ---------------------------------------

def test_pg_get_selects_with_expiry_filter():
    runtime = _FakeRuntime(fetch=("vendas",))
    store = PgSessionDomainStore(runtime)
    assert store.get("whatsapp:hermes:abc") == "vendas"
    sql, params = runtime.calls[-1]
    assert "FROM session_domain_binding" in sql
    assert "expires_at > now()" in sql
    assert params == ("whatsapp:hermes:abc",)


def test_pg_get_returns_none_when_absent():
    runtime = _FakeRuntime(fetch=None)
    store = PgSessionDomainStore(runtime)
    assert store.get("whatsapp:hermes:abc") is None


def test_pg_set_upserts_with_ttl():
    runtime = _FakeRuntime()
    store = PgSessionDomainStore(runtime, ttl_seconds=1800)
    store.set("whatsapp:hermes:abc", "vendas")
    sql, params = runtime.calls[-1]
    assert "INSERT INTO session_domain_binding" in sql
    assert "ON CONFLICT (session_id_hash) DO UPDATE" in sql
    assert "make_interval(secs => %s)" in sql
    assert params == ("whatsapp:hermes:abc", "vendas", 1800)


def test_pg_set_without_ttl_writes_null_expiry():
    runtime = _FakeRuntime()
    store = PgSessionDomainStore(runtime, ttl_seconds=0)
    store.set("whatsapp:hermes:abc", "vendas")
    sql, params = runtime.calls[-1]
    assert "VALUES (%s, %s, now(), NULL)" in sql
    assert params == ("whatsapp:hermes:abc", "vendas")


def test_pg_clear_deletes_by_key():
    runtime = _FakeRuntime()
    store = PgSessionDomainStore(runtime)
    store.clear("whatsapp:hermes:abc")
    sql, params = runtime.calls[-1]
    assert "DELETE FROM session_domain_binding" in sql
    assert params == ("whatsapp:hermes:abc",)


# --- guards and fail-open --------------------------------------------------

@pytest.mark.parametrize("session_id", ["", None])
def test_pg_empty_session_id_is_noop(session_id):
    runtime = _FakeRuntime()
    store = PgSessionDomainStore(runtime)
    assert store.get(session_id) is None
    store.set(session_id, "vendas")
    store.clear(session_id)
    assert runtime.calls == []


def test_pg_noop_when_persistence_disabled():
    runtime = _FakeRuntime(persistence_enabled=False)
    store = PgSessionDomainStore(runtime)
    assert store.get("whatsapp:hermes:abc") is None
    store.set("whatsapp:hermes:abc", "vendas")
    store.clear("whatsapp:hermes:abc")
    assert runtime.calls == []


def test_pg_fail_open_on_database_unavailable():
    runtime = _FakeRuntime(raise_unavailable=True)
    store = PgSessionDomainStore(runtime)
    # get degrades to None; set/clear swallow the error (no exception leaks).
    assert store.get("whatsapp:hermes:abc") is None
    store.set("whatsapp:hermes:abc", "vendas")
    store.clear("whatsapp:hermes:abc")


def test_pg_set_skips_empty_domain():
    runtime = _FakeRuntime()
    store = PgSessionDomainStore(runtime)
    store.set("whatsapp:hermes:abc", "")
    assert runtime.calls == []
