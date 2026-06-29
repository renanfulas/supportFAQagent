import time
from types import SimpleNamespace

import pytest

from app.conversations.service import hash_session
from app.conversations.session_state import (
    InMemorySessionStateStore,
    SessionState,
    SessionStateStore,
    build_session_state_store_from_env,
)
from app.core.config import get_settings
from app.orchestration.chat_flow import ChatFlowService


def _state(label: str = "answered", domain: str = "vendas", conf: float = 0.5) -> SessionState:
    return SessionState(state=label, domain=domain, confidence=conf, updated_at=time.time())


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


# --- InMemorySessionStateStore ------------------------------------------------

def test_put_get_roundtrip() -> None:
    store = InMemorySessionStateStore()
    st = _state()
    store.put(domain="vendas", channel="whatsapp", session_hash="abc", state=st, ttl_seconds=60)
    assert store.get(domain="vendas", channel="whatsapp", session_hash="abc") == st


def test_isolation_by_domain_channel_hash() -> None:
    store = InMemorySessionStateStore()
    store.put(domain="vendas", channel="whatsapp", session_hash="abc", state=_state(), ttl_seconds=60)
    assert store.get(domain="suporte", channel="whatsapp", session_hash="abc") is None
    assert store.get(domain="vendas", channel="web", session_hash="abc") is None
    assert store.get(domain="vendas", channel="whatsapp", session_hash="xyz") is None


def test_ttl_expiry() -> None:
    clock = _Clock()
    store = InMemorySessionStateStore(time_fn=clock)
    store.put(domain="vendas", channel="whatsapp", session_hash="abc", state=_state(), ttl_seconds=60)
    clock.t += 59
    assert store.get(domain="vendas", channel="whatsapp", session_hash="abc") is not None
    clock.t += 2
    assert store.get(domain="vendas", channel="whatsapp", session_hash="abc") is None


def test_ttl_zero_never_expires() -> None:
    clock = _Clock()
    store = InMemorySessionStateStore(time_fn=clock)
    store.put(domain="vendas", channel="whatsapp", session_hash="abc", state=_state(), ttl_seconds=0)
    clock.t += 100_000
    assert store.get(domain="vendas", channel="whatsapp", session_hash="abc") is not None


def test_clear() -> None:
    store = InMemorySessionStateStore()
    store.put(domain="vendas", channel="whatsapp", session_hash="abc", state=_state(), ttl_seconds=60)
    store.clear(domain="vendas", channel="whatsapp", session_hash="abc")
    assert store.get(domain="vendas", channel="whatsapp", session_hash="abc") is None


# --- build_session_state_store_from_env --------------------------------------

def test_build_from_env_memory_and_protocol() -> None:
    store = build_session_state_store_from_env(getenv=lambda k, d="": "memory")
    assert isinstance(store, InMemorySessionStateStore)
    assert isinstance(store, SessionStateStore)


def test_build_from_env_defaults_to_memory() -> None:
    assert isinstance(build_session_state_store_from_env(getenv=lambda k, d="": d), InMemorySessionStateStore)


def test_build_from_env_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError):
        build_session_state_store_from_env(getenv=lambda k, d="": "mongodb")


def test_build_from_env_redis_not_implemented_yet() -> None:
    with pytest.raises(NotImplementedError):
        build_session_state_store_from_env(getenv=lambda k, d="": "redis")


# --- ChatFlowService integration (write path, fail-open) ---------------------

def _hash(session_id: str) -> str:
    return hash_session(session_id, get_settings().persistence_hash_secret or "")


def test_record_session_state_writes() -> None:
    store = InMemorySessionStateStore()
    flow = ChatFlowService(session_state_store=store)
    flow._record_session_state(
        domain=SimpleNamespace(name="vendas"),
        session_id="whatsapp:hermes:abc",
        channel="whatsapp",
        result={"domain": "vendas", "confidence": 0.42, "escalated": True},
    )
    st = store.get(domain="vendas", channel="whatsapp", session_hash=_hash("whatsapp:hermes:abc"))
    assert st is not None
    assert st.state == "escalated"
    assert st.confidence == 0.42


def test_record_session_state_noop_without_store() -> None:
    ChatFlowService()._record_session_state(
        domain=SimpleNamespace(name="vendas"),
        session_id="web:1",
        channel="web",
        result={"escalated": False},
    )  # must not raise


def test_record_session_state_noop_without_session_id() -> None:
    store = InMemorySessionStateStore()
    ChatFlowService(session_state_store=store)._record_session_state(
        domain=SimpleNamespace(name="vendas"),
        session_id=None,
        channel="web",
        result={"escalated": False},
    )
    assert store.get(domain="vendas", channel="web", session_hash=_hash("x")) is None


def test_record_session_state_fail_open() -> None:
    class _BoomStore:
        def get(self, **kwargs):
            return None

        def put(self, **kwargs):
            raise RuntimeError("redis down")

        def clear(self, **kwargs):
            pass

    # Must swallow the store error: the hot tier is non-authoritative.
    ChatFlowService(session_state_store=_BoomStore())._record_session_state(
        domain=SimpleNamespace(name="vendas"),
        session_id="web:1",
        channel="web",
        result={"escalated": False},
    )


def test_answer_wrapper_records_state(monkeypatch) -> None:
    store = InMemorySessionStateStore()
    flow = ChatFlowService(session_state_store=store)
    monkeypatch.setattr(
        flow,
        "_answer_inner",
        lambda *a, **k: {"domain": "vendas", "confidence": 0.7, "escalated": False},
    )
    out = flow.answer(SimpleNamespace(name="vendas"), "oi", session_id="web:123", channel="web")
    assert out["confidence"] == 0.7
    st = store.get(domain="vendas", channel="web", session_hash=_hash("web:123"))
    assert st is not None and st.state == "answered"
