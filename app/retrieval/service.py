from app.core.errors import RetrievalError
from app.domain_engine.models import DomainConfig
from app.retrieval.embeddings import get_domain_embeddings
from app.retrieval.lexical_store import LexicalVectorStore
from app.retrieval.models import RetrievedChunk
from app.retrieval.vector_store import VectorStore


def build_vector_store(domain: DomainConfig) -> VectorStore:
    """Factory: resolve embeddings do domínio e retorna o VectorStore ativo.

    get_domain_embeddings está conectado aqui e pronto para ser passado
    ao adapter pgvector na Fase 3. LexicalVectorStore é o caminho ativo
    até a integração com pgvector.
    """
    embedding_fn = get_domain_embeddings(domain)

    # Fase 3 — substituir por:
    # return PgVectorStore(embedding_function=embedding_fn)
    _ = embedding_fn
    return LexicalVectorStore()


class RetrievalService:
    """Retrieval facade for the current store adapter."""

    def __init__(self, vector_store: VectorStore | None = None) -> None:
        self.vector_store = vector_store or LexicalVectorStore()

    def retrieve(self, domain: DomainConfig, question: str) -> list[RetrievedChunk]:
        try:
            return self.vector_store.search(
                domain=domain,
                query=question,
                top_k=domain.response.max_context_chunks,
            )
        except Exception as exc:
            raise RetrievalError("retrieval failed") from exc