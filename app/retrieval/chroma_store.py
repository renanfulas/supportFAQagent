from langchain_community.vectorstores import Chroma

from app.domain_engine.models import DomainConfig
from app.retrieval.models import RetrievedChunk
from app.retrieval.vector_store import VectorStore


class ChromaStore(VectorStore):
    def __init__(self, persist_directory: str, embedding_function):
        self.persist_directory = persist_directory
        self.embedding_function = embedding_function
        self.vector_store = Chroma(
            persist_directory=self.persist_directory,
            embedding_function=self.embedding_function,
        )

    def add_documents(self, docs):
        self.vector_store.add_documents(docs)

    def similarity_search_with_score(self, query: str, top_k: int = 5):
        return self.vector_store.similarity_search_with_score(query, k=top_k)

    def search(
        self,
        domain: DomainConfig,
        query: str,
        top_k: int,
    ) -> list[RetrievedChunk]:
        _ = domain
        results = self.similarity_search_with_score(query=query, top_k=top_k)

        chunks: list[RetrievedChunk] = []
        for document, distance in results:
            metadata = document.metadata or {}
            chunks.append(
                RetrievedChunk(
                    source=str(metadata.get("source", "")),
                    title=str(metadata.get("title", "Chroma document")),
                    text=document.page_content,
                    score=max(0.0, 1.0 - float(distance)),
                )
            )

        return chunks
