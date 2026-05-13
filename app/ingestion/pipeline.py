from app.ingestion.ticket_loader import load_tickets_from_csv
from app.retrieval.chroma_store import ChromaStore
from app.ingestion.chunking import split_documents_to_dicts

def ingest_csv_to_chroma(csv_filepath: str, chroma_store: ChromaStore):
    """
    Carrega o CSV, faz o chunking do texto isolando objetos do LangChain
    e salva no ChromaDB usando os dicionários puros resultantes.
    """
    # 1. Carregar documentos (ainda usa o loader local, que pode retornar Docs ou Textos)
    docs = load_tickets_from_csv(csv_filepath)
    
    if not docs:
        print("Nenhum documento encontrado no CSV.")
        return 0

    # 2. Text Splitter - Chunking independente de Document no output
    chunks = split_documents_to_dicts(docs, chunk_size=1000, chunk_overlap=150)
    
    print(f"Dividido em {len(chunks)} chunks.")
    
    # 3. Adicionar ao Chroma
    chroma_store.add_chunks(chunks)
    
    print(f"Ingestão concluída. {len(chunks)} chunks adicionados ao ChromaDB.")
    return len(chunks)
