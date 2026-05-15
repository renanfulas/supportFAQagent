from app.core.errors import RetrievalError
from app.domain_engine.models import DomainConfig
from app.retrieval.lexical_store import LexicalVectorStore
from app.retrieval.models import RetrievedChunk
from app.retrieval.vector_store import VectorStore


def build_vector_store(domain: DomainConfig) -> VectorStore:
    """Factory: retorna o VectorStore ativo para o dominio.

    LexicalVectorStore e o caminho ativo ate a integracao com pgvector. Nao
    resolvemos embeddings aqui enquanto o caminho ativo for lexical, para evitar
    exigir credencial de provider antes do adapter vetorial oficial entrar.
    """
    _ = domain

    # Fase 3: substituir por:
    # embedding_fn = get_domain_embeddings(domain)
    # return PgVectorStore(embedding_function=embedding_fn)
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
        except RetrievalError:
            raise
        except Exception as exc:
            raise RetrievalError("retrieval failed") from exc
