import pandas as pd
from langchain_core.documents import Document

def load_tickets_from_csv(filepath: str) -> list[Document]:
    """
    Lê um CSV de chamados e retorna uma lista de Documentos.
    Espera-se que o CSV tenha colunas como 'titulo' e 'conteudo', ou 'dialogo'.
    """
    df = pd.read_csv(filepath)
    docs = []
    for _, row in df.iterrows():
        # Vamos usar um formato simples agregando tudo
        content = f"Título: {row.get('titulo', 'Sem título')}\n\n{row.get('conteudo', '')}"
        
        # Meta-dados podem incluir informações do chamado
        metadata = {
            "source": filepath,
            "id": str(row.get('id', '')),
        }
        
        doc = Document(page_content=content, metadata=metadata)
        docs.append(doc)
    
    return docs
