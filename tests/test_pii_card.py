"""Unit tests for PAN (card number) detection and redaction (WS-1).

Covers the Luhn-validated detector in ``app.core.persistence_sanitize``:
- accepts a valid PAN;
- rejects non-Luhn 16-digit runs, boleto linha digitavel, CPF and CNPJ;
- ``contains_card_number`` true/false cases;
- redaction replaces the PAN in persisted/logged text without echoing it.

No real card numbers are used: ``4111 1111 1111 1111`` is the public Visa test
PAN and never references a live account.
"""
from app.core.persistence_sanitize import (
    REDACTED_CARD,
    contains_card_number,
    sanitize_for_persistence,
)


VALID_PAN = "4111 1111 1111 1111"  # public Visa test PAN, passes Luhn
VALID_PAN_DASHES = "5500-0000-0000-0004"  # public Mastercard test PAN
NON_LUHN_16 = "1234 5678 9012 3456"  # random-ish 16 digits, fails Luhn
BOLETO_LINHA = "34191790010104351004791020150008291070026000"  # 44 digits
CPF = "529.982.247-25"  # valid CPF (11 digits)
CNPJ = "11.222.333/0001-81"  # valid CNPJ (14 digits)


def test_luhn_accepts_valid_pan() -> None:
    assert contains_card_number(VALID_PAN) is True
    assert contains_card_number(VALID_PAN_DASHES) is True


def test_rejects_non_luhn_sixteen_digits() -> None:
    assert contains_card_number(NON_LUHN_16) is False


def test_rejects_boleto_linha_digitavel() -> None:
    assert contains_card_number(BOLETO_LINHA) is False
    assert contains_card_number("Linha digitavel: " + BOLETO_LINHA) is False


def test_rejects_cpf() -> None:
    assert contains_card_number(CPF) is False
    assert contains_card_number("52998224725") is False


def test_rejects_cnpj() -> None:
    assert contains_card_number(CNPJ) is False
    assert contains_card_number("11222333000181") is False


def test_rejects_repeated_digit_order_id() -> None:
    # An order id of a single repeated digit is not a PAN even if it would pass
    # Luhn by construction.
    assert contains_card_number("0000000000000000") is False


def test_contains_card_number_false_on_empty_and_prose() -> None:
    assert contains_card_number("") is False
    assert contains_card_number(None) is False
    assert contains_card_number("quero contratar o plano de hospedagem") is False


def test_contains_card_number_in_natural_sentence() -> None:
    assert contains_card_number("segue meu cartao 4111 1111 1111 1111") is True


def test_redaction_replaces_pan_in_persisted_text() -> None:
    sanitized = sanitize_for_persistence(
        "pode cobrar no cartao 4111 1111 1111 1111 hoje?"
    )
    assert sanitized is not None
    assert REDACTED_CARD in sanitized
    assert "4111" not in sanitized
    assert "1111" not in sanitized
    # surrounding prose is preserved
    assert "pode cobrar no cartao" in sanitized


def test_redaction_handles_dashed_pan() -> None:
    sanitized = sanitize_for_persistence("cartao 5500-0000-0000-0004")
    assert sanitized is not None
    assert REDACTED_CARD in sanitized
    assert "5500" not in sanitized


def test_redaction_does_not_card_flag_boleto_and_cnpj() -> None:
    # Boleto/CNPJ must not be classified as card data. (They may still be caught
    # by the pre-existing phone/IP rules, which is acceptable; the WS-1 guarantee
    # is only that they are never REDACTED_CARD.)
    text = f"boleto {BOLETO_LINHA} e cnpj {CNPJ}"
    sanitized = sanitize_for_persistence(text)
    assert sanitized is not None
    assert REDACTED_CARD not in sanitized


def test_redaction_is_idempotent() -> None:
    once = sanitize_for_persistence("cartao 4111 1111 1111 1111")
    twice = sanitize_for_persistence(once)
    assert once == twice
