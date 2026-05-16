from pathlib import Path

from app.domain_engine.models import DomainConfig
from app.ingestion.chunking import split_text
from app.ingestion.models import KnowledgeChunk, KnowledgeDocument


class IngestionService:
    def load_domain_documents(self, domain: DomainConfig) -> list[KnowledgeDocument]:
        documents: list[KnowledgeDocument] = []

        for source in domain.knowledge.sources:
            base_path = domain.root_path / source
            if not base_path.exists():
                continue

            for file_path in sorted(base_path.rglob("*"), key=lambda path: path.as_posix()):
                if not file_path.is_file() or file_path.suffix.lower() not in {
                    ".md",
                    ".txt",
                }:
                    continue

                documents.append(self._read_document(file_path))

        return documents

    def chunk_documents(
        self,
        documents: list[KnowledgeDocument],
        chunk_size: int = 800,
    ) -> list[KnowledgeChunk]:
        chunks: list[KnowledgeChunk] = []

        for document in documents:
            parts = split_text(document.content, chunk_size=chunk_size)
            for part in parts:
                chunks.append(
                    KnowledgeChunk(
                        source=document.source,
                        title=document.title,
                        text=part["chunk_text"],
                        chunk_index=part["chunk_index"],
                    )
                )

        return chunks

    def _read_document(self, file_path: Path) -> KnowledgeDocument:
        content = file_path.read_text(encoding="utf-8")
        title = file_path.stem.replace("-", " ").replace("_", " ").title()
        return KnowledgeDocument(
            source=str(file_path),
            title=title,
            content=content.strip(),
        )
