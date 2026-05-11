from pathlib import Path

from app.domain_engine.models import DomainConfig
from app.ingestion.models import KnowledgeChunk, KnowledgeDocument


class IngestionService:
    def load_domain_documents(self, domain: DomainConfig) -> list[KnowledgeDocument]:
        documents: list[KnowledgeDocument] = []

        for source in domain.knowledge.sources:
            base_path = domain.root_path / source
            if not base_path.exists():
                continue

            for file_path in base_path.rglob("*"):
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
            parts = self._split_text(document.content, chunk_size=chunk_size)
            for index, part in enumerate(parts):
                chunks.append(
                    KnowledgeChunk(
                        source=document.source,
                        title=document.title,
                        text=part,
                        chunk_index=index,
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

    def _split_text(self, text: str, chunk_size: int) -> list[str]:
        normalized = " ".join(text.split())
        if len(normalized) <= chunk_size:
            return [normalized] if normalized else []

        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            end = start + chunk_size
            chunks.append(normalized[start:end].strip())
            start = end
        return chunks
