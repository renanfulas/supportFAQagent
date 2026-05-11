from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.ingestion.ticket_loader import load_tickets_from_csv
from app.retrieval.chroma_store import ChromaStore

def ingest_csv_to_chroma(csv_filepath: str, chroma_store: ChromaStore):
    """
    Carrega o CSV, faz o chunking do texto e salva no ChromaDB.
    """
    # 1. Carregar documentos
    docs = load_tickets_from_csv(csv_filepath)
    
    if not docs:
        print("Nenhum documento encontrado no CSV.")
        return 0

    # 2. Text Splitter - Chunking
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
        separators=["\n\n", "\n", " ", ""]
    )
    
    chunks = text_splitter.split_documents(docs)
    
    print(f"Dividido em {len(chunks)} chunks.")
    
    # 3. Adicionar ao Chroma
    chroma_store.add_documents(chunks)
    
    print(f"Ingestão concluída. {len(chunks)} chunks adicionados ao ChromaDB.")
    return len(chunks)
