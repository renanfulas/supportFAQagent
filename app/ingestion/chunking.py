from typing import Any

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ModuleNotFoundError:  # pragma: no cover - compatibility fallback
    try:
        from langchain.text_splitter import RecursiveCharacterTextSplitter
    except ModuleNotFoundError:  # pragma: no cover - optional dependency
        RecursiveCharacterTextSplitter = None


def split_text(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Divide um texto em chunks menores usando LangChain internamente,
    mas retorna dicionarios puros para evitar acoplamento com Document.
    """
    chunk_metadata = dict(metadata or {})
    docs = _create_documents([text], chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    chunks: list[dict[str, Any]] = []
    for index, doc in enumerate(docs):
        chunks.append(
            {
                "chunk_index": index,
                "chunk_text": doc.page_content,
                "metadata": chunk_metadata,
                "token_estimate": len(doc.page_content) // 4,
            }
        )

    return chunks


def split_documents_to_dicts(
    documents: list[Any],
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
) -> list[dict[str, Any]]:
    """
    Recebe documentos do LangChain e converte o resultado em dicionarios
    padrao do sistema com metadados preservados.
    """
    split_docs = _split_documents(
        documents,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    chunks: list[dict[str, Any]] = []
    for index, doc in enumerate(split_docs):
        chunks.append(
            {
                "chunk_index": index,
                "chunk_text": doc.page_content,
                "metadata": dict(doc.metadata or {}),
                "token_estimate": len(doc.page_content) // 4,
            }
        )

    return chunks


def _create_documents(
    texts: list[str],
    chunk_size: int,
    chunk_overlap: int,
) -> list[Any]:
    safe_overlap = min(chunk_overlap, max(0, chunk_size - 1))
    if RecursiveCharacterTextSplitter is not None:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=safe_overlap,
            separators=["\n\n", "\n", " ", ""],
        )
        return splitter.create_documents(texts)

    return [_SimpleDocument(page_content=part, metadata={}) for text in texts for part in _split_string(text, chunk_size, safe_overlap)]


def _split_documents(
    documents: list[Any],
    chunk_size: int,
    chunk_overlap: int,
) -> list[Any]:
    safe_overlap = min(chunk_overlap, max(0, chunk_size - 1))
    if RecursiveCharacterTextSplitter is not None:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=safe_overlap,
            separators=["\n\n", "\n", " ", ""],
        )
        return splitter.split_documents(documents)

    chunks: list[Any] = []
    for document in documents:
        metadata = dict(getattr(document, "metadata", {}) or {})
        page_content = getattr(document, "page_content", "")
        for part in _split_string(page_content, chunk_size, safe_overlap):
            chunks.append(_SimpleDocument(page_content=part, metadata=metadata))
    return chunks


def _split_string(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    if len(normalized) <= chunk_size:
        return [normalized]

    step = max(1, chunk_size - chunk_overlap)
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = start + chunk_size
        part = normalized[start:end].strip()
        if part:
            chunks.append(part)
        start += step
    return chunks


class _SimpleDocument:
    def __init__(self, page_content: str, metadata: dict[str, Any]) -> None:
        self.page_content = page_content
        self.metadata = metadata