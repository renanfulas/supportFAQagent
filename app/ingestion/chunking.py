from typing import Any, Dict, List
from langchain_text_splitters import RecursiveCharacterTextSplitter

def split_text(
    text: str, 
    chunk_size: int = 1000, 
    chunk_overlap: int = 150, 
    metadata: Dict[str, Any] = None
) -> List[Dict[str, Any]]:
    """
    Divide um texto em chunks menores utilizando o LangChain, mas retornando
    uma lista de dicionários padrão Python para evitar o acoplamento do tipo 
    'Document' no restante da arquitetura.
    """
    if metadata is None:
        metadata = {}
        
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""]
    )
    
    # Cria docs para utilizar a lógica do langchain internamente
    docs = splitter.create_documents([text])
    
    chunks = []
    for idx, doc in enumerate(docs):
        chunks.append({
            "chunk_index": idx,
            "chunk_text": doc.page_content,
            "metadata": metadata,
            "token_estimate": len(doc.page_content) // 4
        })
        
    return chunks

def split_documents_to_dicts(documents: List[Any], chunk_size: int = 1000, chunk_overlap: int = 150) -> List[Dict[str, Any]]:
    """
    Recebe uma lista de objetos 'Document' do LangChain (ex: vindo de loaders),
    divide e converte para dicionários padrão do sistema.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""]
    )
    
    split_docs = splitter.split_documents(documents)
    
    chunks = []
    for idx, doc in enumerate(split_docs):
        chunks.append({
            "chunk_index": idx,
            "chunk_text": doc.page_content,
            "metadata": doc.metadata,
            "token_estimate": len(doc.page_content) // 4
        })
        
    return chunks
