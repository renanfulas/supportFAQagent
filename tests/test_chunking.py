from pathlib import Path

from app.ingestion.chunking import split_documents_to_dicts, split_text
from app.ingestion.models import KnowledgeDocument
from app.ingestion.service import IngestionService
from app.domain_engine.models import DomainConfig, DomainKnowledgeConfig


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


def test_split_text_ignores_blank_content() -> None:
    assert split_text(" \n\t ", chunk_size=10, chunk_overlap=0) == []


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


def test_split_documents_to_dicts_resets_indexes_per_document_and_skips_blank() -> None:
    chunks = split_documents_to_dicts(
        [
            StubDocument(page_content="primeiro documento com texto suficiente", metadata={"id": "1"}),
            StubDocument(page_content="   ", metadata={"id": "blank"}),
            StubDocument(page_content="segundo documento com texto suficiente", metadata={"id": "2"}),
        ],
        chunk_size=12,
        chunk_overlap=0,
    )

    indexes_by_document: dict[str, list[int]] = {}
    for chunk in chunks:
        document_id = chunk["metadata"]["id"]
        indexes_by_document.setdefault(document_id, []).append(chunk["chunk_index"])

    assert "blank" not in indexes_by_document
    assert set(indexes_by_document) == {"1", "2"}
    assert indexes_by_document["1"] == list(range(len(indexes_by_document["1"])))
    assert indexes_by_document["2"] == list(range(len(indexes_by_document["2"])))


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


def test_ingestion_service_loads_domain_documents_deterministically(tmp_path: Path) -> None:
    knowledge_path = tmp_path / "knowledge" / "faqs"
    knowledge_path.mkdir(parents=True)
    (knowledge_path / "z-last.md").write_text("ultimo", encoding="utf-8")
    (knowledge_path / "a-first.md").write_text("primeiro", encoding="utf-8")

    domain = DomainConfig(
        name="test-domain",
        display_name="Test Domain",
        root_path=tmp_path,
        knowledge=DomainKnowledgeConfig(sources=["knowledge/faqs"]),
    )

    documents = IngestionService().load_domain_documents(domain)

    assert [Path(document.source).name for document in documents] == [
        "a-first.md",
        "z-last.md",
    ]
