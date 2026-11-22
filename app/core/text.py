import unicodedata


def fold(text: str) -> str:
    """Casefold and strip diacritics so text matching ignores accents and case.

    Single normalization helper for security-relevant term matching (handoff
    patterns, domain terms) and for eval/orchestration comparisons. Patterns and
    domain terms are often written without accents ("ignore suas instrucoes")
    while users type proper pt-BR ("instruções"); folding both sides makes the
    comparison independent of orthography.

    Idempotent: ``fold(fold(x)) == fold(x)``. It does not trim whitespace;
    callers that need it add ``.strip()``.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_accents.casefold()
