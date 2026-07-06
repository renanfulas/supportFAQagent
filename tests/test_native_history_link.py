"""Fase 3 (opcional, opt-in) da ponte WhatsApp<->console: formula de
recalculo do hash nativo e backfill de `customer_id` em
conversations/support_cases.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from app.identity.native_history_link import (
    NativeHistoryLinkRepository,
    NativeSessionHashes,
    compute_native_session_hashes,
)


# --------------------------------------------------------------------------- #
# Formula pura
# --------------------------------------------------------------------------- #


def test_compute_native_session_hashes_matches_real_chat_transport_formula(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: o recalculo precisa bater exatamente com o que
    app/integrations/hermes/chat_transport.py e
    app/integrations/meta_whatsapp/chat_transport.py gravariam para o mesmo
    telefone -- senao o backfill nunca encontra nenhuma conversa.

    ``_safe_*_session_id`` chamam ``hash_sensitive_value`` sem passar
    ``secret=`` explicito -- caem no fallback de
    ``PERSISTENCE_HASH_SECRET`` do ambiente. O monkeypatch garante que esse
    fallback bate com o secret explicito que passamos ao recalculo."""

    from app.conversations.service import hash_session
    from app.integrations.hermes.chat_transport import _safe_hermes_session_id
    from app.integrations.meta_whatsapp.chat_transport import _safe_meta_session_id

    secret = "test-persistence-secret"
    phone = "+5511999999999"
    monkeypatch.setenv("PERSISTENCE_HASH_SECRET", secret)

    expected_hermes = hash_session(_safe_hermes_session_id(phone), secret)
    expected_meta = hash_session(_safe_meta_session_id(phone), secret)

    got = compute_native_session_hashes(phone, persistence_hash_secret=secret)

    assert got.hermes == expected_hermes
    assert got.meta == expected_meta


def test_compute_native_session_hashes_is_deterministic_and_key_scoped() -> None:
    phone = "+5511999999999"

    a = compute_native_session_hashes(phone, persistence_hash_secret="secret-1")
    b = compute_native_session_hashes(phone, persistence_hash_secret="secret-1")
    c = compute_native_session_hashes(phone, persistence_hash_secret="secret-2")
    other_phone = compute_native_session_hashes(
        "+5511999999998", persistence_hash_secret="secret-1"
    )

    assert a == b
    assert a.hermes != c.hermes
    assert a.meta != c.meta
    assert a.hermes != other_phone.hermes


def test_compute_native_session_hashes_hermes_and_meta_differ() -> None:
    got = compute_native_session_hashes(
        "+5511999999999", persistence_hash_secret="secret"
    )

    assert got.hermes != got.meta


# --------------------------------------------------------------------------- #
# Backfill (FakeCursor)
# --------------------------------------------------------------------------- #


class FakeCursor:
    def __init__(self, rowcounts: list[int]) -> None:
        self._rowcounts = list(rowcounts)
        self.executed: list[tuple[str, tuple]] = []
        self.rowcount = 0

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executed.append((sql, params))
        self.rowcount = self._rowcounts.pop(0)


class FakeRuntime:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    @contextmanager
    def transaction(self):
        yield _Connection(self._cursor)


class _Connection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor


HASHES = NativeSessionHashes(hermes="hermes-hash", meta="meta-hash")


def test_link_updates_conversations_and_support_cases_only_where_null() -> None:
    cursor = FakeCursor(rowcounts=[2, 1])
    repo = NativeHistoryLinkRepository(FakeRuntime(cursor))

    result = repo.link(customer_id="cust-1", hashes=HASHES)

    assert result.conversations_linked == 2
    assert result.support_cases_linked == 1
    conv_sql, conv_params = cursor.executed[0]
    assert "UPDATE conversations" in conv_sql
    assert "customer_id IS NULL" in conv_sql
    assert conv_params == ("cust-1", "hermes-hash", "meta-hash")
    case_sql, case_params = cursor.executed[1]
    assert "UPDATE support_cases" in case_sql
    assert "sc.customer_id IS NULL" in case_sql
    assert "FROM conversations" in case_sql
    assert case_params == ("cust-1", "hermes-hash", "meta-hash")


def test_link_zero_matches_returns_zero_counts() -> None:
    cursor = FakeCursor(rowcounts=[0, 0])
    repo = NativeHistoryLinkRepository(FakeRuntime(cursor))

    result = repo.link(customer_id="cust-1", hashes=HASHES)

    assert result.conversations_linked == 0
    assert result.support_cases_linked == 0
