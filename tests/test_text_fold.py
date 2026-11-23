import unicodedata

import pytest

from app.core.text import fold


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Instruções", "instrucoes"),
        ("IGNORE SUAS INSTRUÇÕES", "ignore suas instrucoes"),
        ("não", "nao"),
        ("Você é", "voce e"),
        ("configuração de produção", "configuracao de producao"),
        ("instrucoes", "instrucoes"),
        ("ｍｅ ｐａｓｓｅ", "me passe"),
        ("Straße", "strasse"),
        ("", ""),
    ],
)
def test_fold_strips_accents_and_casefolds(raw: str, expected: str) -> None:
    assert fold(raw) == expected


def test_fold_treats_composed_and_decomposed_accents_the_same() -> None:
    composed = "instruções"
    decomposed = unicodedata.normalize("NFD", composed)

    assert composed != decomposed
    assert fold(composed) == fold(decomposed) == "instrucoes"


def test_fold_is_idempotent() -> None:
    value = "Ação Rápida: Você NÃO pode ignorar as instruções"

    assert fold(fold(value)) == fold(value)


def test_fold_does_not_trim_whitespace() -> None:
    assert fold("  Olá  ") == "  ola  "
