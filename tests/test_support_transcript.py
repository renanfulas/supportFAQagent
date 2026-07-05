"""Cobertura do filtro de roles do transcript (ponte WhatsApp<->console).

``role='agent'`` (resposta humana pela thread de suporte) precisa aparecer no
detalhe do console ao lado de ``user``/``assistant`` (bot); qualquer outra
role (ex.: uma futura 'system') fica de fora.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.support.transcript import count_conversation_turns, fetch_conversation_transcript


class FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows
        self.executed: list[tuple] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executed.append((sql, params))

    def fetchone(self):
        return (len(self.rows),)

    def fetchall(self):
        return self.rows


NOW = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)


def test_fetch_conversation_transcript_includes_agent_role() -> None:
    rows = [
        (1, "user", "minha vps caiu", None, False, [], [], None, NOW),
        (2, "assistant", "vou verificar", 0.4, True, ["low_confidence"], [], None, NOW),
        (3, "agent", "ja resolvi, pode confirmar?", None, False, [], [], None, NOW),
    ]
    cursor = FakeCursor(rows)

    turns = fetch_conversation_transcript(cursor, "conv-1", limit=200)

    assert [turn["role"] for turn in turns] == ["user", "assistant", "agent"]
    sql, params = cursor.executed[0]
    assert "role = ANY(%s)" in sql
    assert params[1] == ["user", "assistant", "agent"]


def test_fetch_conversation_transcript_none_conversation_returns_empty() -> None:
    cursor = FakeCursor([])
    assert fetch_conversation_transcript(cursor, None, limit=200) == []
    assert cursor.executed == []


def test_count_conversation_turns_uses_same_role_set() -> None:
    class _Cursor(FakeCursor):
        def fetchone(self):
            return (3,)

    cursor = _Cursor([])
    count = count_conversation_turns(cursor, "conv-1")

    assert count == 3
    sql, params = cursor.executed[0]
    assert "role = ANY(%s)" in sql
    assert params[1] == ["user", "assistant", "agent"]
