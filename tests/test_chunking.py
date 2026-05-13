from pathlib import Path

from app.ingestion.chunking import split_documents_to_dicts, split_text
from app.ingestion.models import KnowledgeDocument
from app.ingestion.service import IngestionService


class StubDocument:
    def __init__(self, page_content: str, metadata: dict[str, str]) -> None:
        self.page_content = page_content
        self.metadata = metadata


def test_split_text_returns_plain_dict_chunks_with_indexes() -> None:
    chunks = split_text(
        "um texto simples para chunking",
        chunk_size=10,
        chunk_overlap=0,
        metadata={"source": "faq.md"},
    )

    assert chunks
    assert chunks[0]["chunk_index"] == 0
    assert isinstance(chunks[0]["chunk_text"], str)
    assert chunks[0]["metadata"]["source"] == "faq.md"
    assert "token_estimate" in chunks[0]


def test_split_documents_to_dicts_preserves_document_metadata() -> None:
    chunks = split_documents_to_dicts(
        [
            StubDocument(
                page_content="texto de exemplo para testar o splitter",
                metadata={"source": "tickets.csv", "id": "123"},
            )
        ],
        chunk_size=12,
        chunk_overlap=0,
    )

    assert chunks
    assert chunks[0]["metadata"]["source"] == "tickets.csv"
    assert chunks[0]["metadata"]["id"] == "123"


def test_ingestion_service_uses_shared_chunking_contract() -> None:
    service = IngestionService()
    documents = [
        KnowledgeDocument(
            source=str(Path("domains/teste/knowledge/faq.md")),
            title="FAQ",
            content="texto de exemplo para dividir em partes menores",
        )
    ]

    chunks = service.chunk_documents(documents, chunk_size=12)

    assert chunks
    assert chunks[0].source.endswith("faq.md")
    assert chunks[0].title == "FAQ"
    assert chunks[0].chunk_index == 0
