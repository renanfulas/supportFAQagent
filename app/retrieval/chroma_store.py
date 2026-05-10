import os
from langchain_community.vectorstores import Chroma

class ChromaStore:
    def __init__(self, persist_directory: str, embedding_function):
        self.persist_directory = persist_directory
        self.embedding_function = embedding_function
        self.vector_store = Chroma(
            persist_directory=self.persist_directory,
            embedding_function=self.embedding_function
        )

    def add_documents(self, docs):
        self.vector_store.add_documents(docs)

    def similarity_search_with_score(self, query: str, top_k: int = 5):
        # Retorna lista de tuplas (Document, score)
        # No Chroma, score menor geralmente indica maior similaridade dependendo da métrica,
        # mas a abstração do LangChain geralmente padroniza.
        return self.vector_store.similarity_search_with_score(query, k=top_k)
