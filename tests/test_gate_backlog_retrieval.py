from pathlib import Path

import pytest

from app.domain_engine.loader import DomainLoader
from app.retrieval.lexical_store import LexicalVectorStore


@pytest.mark.parametrize(
    ("question", "expected_reference"),
    [
        (
            "Ao conectar por SSH aparece permission denied publickey.",
            "ssh-permission-denied-publickey.md",
        ),
        (
            "Minha VPS ficou sem espaco em disco e nao consigo subir o site.",
            "performance-recursos-vps.md",
        ),
        (
            "Meu site na VPS esta muito lento mesmo com poucos acessos.",
            "site-lento-vps.md",
        ),
        (
            "O banco de dados esta ocupando quase todo o disco da VPS.",
            "performance-recursos-vps.md",
        ),
    ],
)
def test_remaining_gate_backlog_has_deterministic_reference(
    question: str,
    expected_reference: str,
) -> None:
    domain = DomainLoader(Path("domains")).load("suporte-vps-whatsapp")
    assert domain is not None

    results = LexicalVectorStore().search(domain, question, top_k=5)

    assert any(expected_reference in result.source for result in results)
