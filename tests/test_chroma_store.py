import importlib
import sys
import types


class FakeVectorStore:
    def __init__(self, *args, **kwargs) -> None:
        self.calls: list[dict] = []

    def add_texts(self, texts, metadatas) -> None:
        self.calls.append({"texts": texts, "metadatas": metadatas})


def test_add_chunks_preserves_chunk_contract_metadata() -> None:
    fake_vectorstores = types.ModuleType("langchain_community.vectorstores")
    fake_vectorstores.Chroma = FakeVectorStore
    fake_package = types.ModuleType("langchain_community")
    fake_package.vectorstores = fake_vectorstores

    sys.modules["langchain_community"] = fake_package
    sys.modules["langchain_community.vectorstores"] = fake_vectorstores

    chroma_module = importlib.import_module("app.retrieval.chroma_store")
    importlib.reload(chroma_module)

    store = chroma_module.ChromaStore(
        persist_directory="tmp/chroma",
        embedding_function=None,
    )

    store.add_chunks(
        [
            {
                "chunk_text": "primeiro chunk",
                "chunk_index": 2,
                "token_estimate": 5,
                "metadata": {"source": "faq.md", "id": "abc"},
            }
        ]
    )

    assert len(store.vector_store.calls) == 1
    call = store.vector_store.calls[0]
    assert call["texts"] == ["primeiro chunk"]
    assert call["metadatas"] == [
        {
            "source": "faq.md",
            "id": "abc",
            "chunk_index": 2,
            "token_estimate": 5,
        }
    ]
