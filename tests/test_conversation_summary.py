import pytest

from app.conversations.summary import (
    build_summary_prompt,
    build_transcript,
    derive_customer_ref,
    parse_summary_json,
    summarize_turns,
)


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
