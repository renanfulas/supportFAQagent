from app.core.errors import RetrievalError
from app.core.config import get_settings
from app.domain_engine.models import DomainConfig
from app.retrieval.embeddings import get_domain_embeddings
from app.retrieval.lexical_store import LexicalVectorStore
from app.retrieval.models import RetrievedChunk
from app.retrieval.pgvector_store import PgVectorStore, PostgresPgVectorSearchBackend
from app.retrieval.vector_store import VectorStore


def build_vector_store(domain: DomainConfig) -> VectorStore:
    """Factory: retorna o VectorStore ativo para o dominio.

    LexicalVectorStore continua sendo o padrao. PgVectorStore so entra quando o
    ambiente define RETRIEVAL_BACKEND=pgvector, evitando exigir DATABASE_URL ou
    credencial de embeddings no caminho local/temporario.
    """
    backend_name = get_settings().retrieval_backend.lower().strip()
    if backend_name == "pgvector":
        return PgVectorStore(
            embedding_function=get_domain_embeddings(domain),
            search_backend=PostgresPgVectorSearchBackend(),
        )
    if backend_name != "lexical":
        raise RetrievalError(f"retrieval backend {backend_name} is not supported")

    return LexicalVectorStore()


class RetrievalService:
    """Retrieval facade for the current store adapter."""

    def __init__(self, vector_store: VectorStore | None = None) -> None:
        self.vector_store = vector_store

    def retrieve(self, domain: DomainConfig, question: str) -> list[RetrievedChunk]:
        try:
            vector_store = self.vector_store or build_vector_store(domain)
            return vector_store.search(
                domain=domain,
                query=question,
                top_k=domain.response.max_context_chunks,
            )
        except RetrievalError:
            raise
        except Exception as exc:
            raise RetrievalError("retrieval failed") from exc
