"""Unit tests for the deterministic checkout intercept in ChatFlowService.

The intercept must fire on payment intent (Pix/cartao/link), never echo the inbound
message (so a pasted card number is not repeated), and yield to the safety path when
the lead asks the bot to store a card number or requests a human.
"""
from pathlib import Path

from app.domain_engine.models import (
    DomainCheckoutConfig,
    DomainConfig,
    DomainHandoffConfig,
)
from app.orchestration.chat_flow import ChatFlowService
from app.retrieval.models import RetrievedChunk


PAYMENT_LINK = "https://www.linkparapagamento.com.br"


def make_vendas_domain() -> DomainConfig:
    return DomainConfig(
        name="vendas",
        display_name="Vendas HostGator",
        root_path=Path("."),
        handoff=DomainHandoffConfig(
            explicit_human_phrases=["atendente", "vendedor humano", "atendimento humano"],
        ),
        checkout=DomainCheckoutConfig(
            enabled=True,
            payment_link=PAYMENT_LINK,
            message="Certo\n\nSeu link foi gerado {link}",
            intent_phrases=["pix", "cartao", "cartão", "quero pagar", "gerar o link"],
            decline_phrases=["numero do cartao", "anotar", "chave api"],
        ),
    )


class _StubRetrieval:
    def retrieve(self, domain: DomainConfig, question: str) -> list[RetrievedChunk]:
        return [RetrievedChunk(source="s.md", title="S", text="ctx", score=1.0)]


def _service() -> ChatFlowService:
    service = ChatFlowService()
    service.retrieval_service = _StubRetrieval()
    return service


def test_checkout_fires_on_card_choice() -> None:
    res = _service().answer(domain=make_vendas_domain(), question="cartão", request_id="r")
    assert res["answer"] == f"Certo\n\nSeu link foi gerado {PAYMENT_LINK}"
    assert res["escalated"] is False
    assert res["handoff_reasons"] == []


def test_checkout_fires_on_pix_and_link_intent() -> None:
    for q in ["Pix", "quero pagar agora", "pode gerar o link?"]:
        res = _service().answer(domain=make_vendas_domain(), question=q, request_id="r")
        assert PAYMENT_LINK in res["answer"], q


def test_checkout_yields_and_does_not_echo_card_number() -> None:
    # WS-1: a pasted PAN must yield to the safety path (no payment link), escalate
    # with card_data, and never echo the card data back.
    res = _service().answer(
        domain=make_vendas_domain(),
        question="segue meu cartao 4111 1111 1111 1111, pode cobrar?",
        request_id="r",
    )
    assert PAYMENT_LINK not in res["answer"]
    assert "4111" not in res["answer"]
    assert "1111" not in res["answer"]
    assert res["escalated"] is True
    assert "card_data" in res["handoff_reasons"]
    # coaching message present, without echoing the data
    assert "cartao" in res["answer"].lower()


def test_checkout_yields_to_safety_when_storing_card_number() -> None:
    # "anotar meu numero do cartao" is a decline phrase -> normal safety path runs,
    # so the deterministic link is NOT returned.
    res = _service().answer(
        domain=make_vendas_domain(),
        question="pode anotar meu numero do cartao de credito para cobrar?",
        request_id="r",
    )
    assert PAYMENT_LINK not in res["answer"]


def test_checkout_yields_to_explicit_human_request() -> None:
    res = _service().answer(
        domain=make_vendas_domain(),
        question="quero pagar mas me passa para um atendente",
        request_id="r",
    )
    assert PAYMENT_LINK not in res["answer"]
    assert res["escalated"] is True


def test_checkout_disabled_domain_is_inert() -> None:
    domain = DomainConfig(name="x", display_name="X", root_path=Path("."))
    res = _service().answer(domain=domain, question="cartão", request_id="r")
    assert PAYMENT_LINK not in res["answer"]


class _FakeHistory:
    def __init__(self, messages: list[dict[str, str]]) -> None:
        self._messages = messages

    def load_recent(self, **kwargs) -> list[dict[str, str]]:
        return self._messages


def _domain_with_value_template() -> DomainConfig:
    base = make_vendas_domain()
    return base.model_copy(
        update={
            "checkout": base.checkout.model_copy(
                update={"message": "Garantindo agora.\n{value}\nLink: {link}"}
            )
        }
    )


def test_checkout_restates_last_quoted_value() -> None:
    service = _service()
    service.history_service = _FakeHistory(
        [
            {"role": "user", "content": "site de farmacia, ~100 visitas/dia"},
            {
                "role": "assistant",
                "content": (
                    "Recomendo o Plano M: de R$ 50,39 por R$ 11,59/mes (77% OFF), "
                    "equivale a R$ 415,69 em 3 anos.\nAte 120 mil visitas/mes, 100 GB NVMe."
                ),
            },
        ]
    )
    res = service.answer(
        domain=_domain_with_value_template(), question="vou de cartão", request_id="r"
    )
    assert "R$ 11,59" in res["answer"]
    assert "R$ 415,69" in res["answer"]
    assert PAYMENT_LINK in res["answer"]


def test_checkout_drops_value_line_without_history() -> None:
    # ChatFlowService() has no history_service -> no value recalled.
    res = _service().answer(
        domain=_domain_with_value_template(), question="pix", request_id="r"
    )
    assert "{value}" not in res["answer"]
    assert PAYMENT_LINK in res["answer"]
    # placeholder line removed cleanly, no blank gap left behind
    assert "\n\n" not in res["answer"].replace("Garantindo agora.\nLink:", "")
