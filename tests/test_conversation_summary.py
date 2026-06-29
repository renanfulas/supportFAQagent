from types import SimpleNamespace

import pytest

import app.core.config as cfg
from app.conversations.summary import (
    ConversationSummaryRecord,
    SummaryRecallService,
    build_summary_prompt,
    build_transcript,
    derive_customer_ref,
    format_summary_for_prompt,
    parse_summary_json,
    summarize_turns,
)
from app.orchestration.chat_flow import ChatFlowService


CARD = "4111 1111 1111 1111"  # valid Luhn test PAN


class _CapturingProvider:
    def __init__(self, response: str) -> None:
        self.response = response
        self.last_prompt: str | None = None

    def generate_answer(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self.response


def test_build_transcript_labels_and_redacts_pan() -> None:
    transcript = build_transcript([("user", f"meu cartao e {CARD}"), ("assistant", "ok")])
    assert "Cliente:" in transcript and "Agente:" in transcript
    assert CARD not in transcript  # PAN redacted before it can reach the model


def test_summarize_turns_redacts_before_model() -> None:
    provider = _CapturingProvider('{"problem":"p","solution":"s","status":"resolvido"}')
    summarize_turns(turns=[("user", f"pague no {CARD}")], provider=provider)
    assert provider.last_prompt is not None
    assert CARD not in provider.last_prompt


def test_parse_summary_json_extracts_from_noise() -> None:
    raw = 'Claro!\n{"problem": "DNS nao propagava", "solution": "ajustou ns", "status": "RESOLVIDO"} fim'
    parsed = parse_summary_json(raw)
    assert parsed["problem"] == "DNS nao propagava"
    assert parsed["status"] == "resolvido"


def test_parse_summary_json_invalid_status_falls_back() -> None:
    parsed = parse_summary_json('{"problem": "x", "solution": "y", "status": "pendente"}')
    assert parsed["status"] == "em_aberto"


def test_parse_summary_json_requires_problem() -> None:
    with pytest.raises(ValueError):
        parse_summary_json('{"problem": "", "solution": "y", "status": "resolvido"}')


def test_parse_summary_json_requires_json() -> None:
    with pytest.raises(ValueError):
        parse_summary_json("desculpe, nao consegui resumir")


def test_summarize_turns_returns_structured() -> None:
    provider = _CapturingProvider('{"problem":"p","solution":"s","status":"escalado"}')
    out = summarize_turns(turns=[("user", "oi"), ("assistant", "ola")], provider=provider)
    assert out == {"problem": "p", "solution": "s", "status": "escalado"}


def test_build_summary_prompt_contains_transcript() -> None:
    prompt = build_summary_prompt("Cliente: oi\nAgente: ola")
    assert "Cliente: oi" in prompt and "JSON" in prompt


def test_derive_customer_ref_prefers_customer_id() -> None:
    assert derive_customer_ref("cust-123", "hash-abc") == "cust-123"
    assert derive_customer_ref(None, "hash-abc") == "hash-abc"
    assert derive_customer_ref(None, None) == "unknown"


# --- Fase 4: recall into the prompt -----------------------------------------

def _record() -> ConversationSummaryRecord:
    return ConversationSummaryRecord(
        domain="d", customer_ref="c", problem="P", solution="S", status="resolvido",
        source_turn_count=3, redaction_version="phase0-v1", model="m", conversation_key="k",
    )


def test_format_summary_for_prompt() -> None:
    s = format_summary_for_prompt(_record())
    assert "Problema: P" in s and "Solucao: S" in s and "Status: resolvido" in s


def test_recall_returns_none_without_customer_ref() -> None:
    class _Runtime:
        def transaction(self):
            raise AssertionError("must not touch the DB without a customer_ref")

    assert SummaryRecallService(_Runtime()).latest_for(domain="d", customer_ref=None) is None


def test_recall_is_fail_open_on_db_error() -> None:
    class _Runtime:
        def transaction(self):
            raise RuntimeError("db down")

    assert SummaryRecallService(_Runtime()).latest_for(domain="d", customer_ref="c") is None


def test_chat_flow_recall_noop_without_service() -> None:
    out = ChatFlowService()._recall_customer_summary(
        domain=SimpleNamespace(name="d"), session_id="s", customer_id=None
    )
    assert out is None


def test_chat_flow_recall_gated_off_by_flag(monkeypatch) -> None:
    calls = {"n": 0}

    class _Recall:
        def latest_for(self, **kwargs):
            calls["n"] += 1
            return "X"

    monkeypatch.setattr(
        cfg, "get_settings",
        lambda: SimpleNamespace(enable_summary_recall=False, persistence_hash_secret=""),
    )
    flow = ChatFlowService(summary_recall=_Recall())
    assert flow._recall_customer_summary(
        domain=SimpleNamespace(name="d"), session_id="s", customer_id="c"
    ) is None
    assert calls["n"] == 0


def test_chat_flow_recall_on_prefers_customer_id(monkeypatch) -> None:
    class _Recall:
        def __init__(self):
            self.args = None

        def latest_for(self, *, domain, customer_ref):
            self.args = (domain, customer_ref)
            return "Problema: X"

    monkeypatch.setattr(
        cfg, "get_settings",
        lambda: SimpleNamespace(enable_summary_recall=True, persistence_hash_secret="secret"),
    )
    recall = _Recall()
    out = ChatFlowService(summary_recall=recall)._recall_customer_summary(
        domain=SimpleNamespace(name="vendas"), session_id="web:1", customer_id="cust-9"
    )
    assert out == "Problema: X"
    assert recall.args == ("vendas", "cust-9")
