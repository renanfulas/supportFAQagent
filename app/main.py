import os
import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from app.llm.wrapper import LLMWrapper
from app.retrieval.embeddings import get_embeddings
from app.retrieval.chroma_store import ChromaStore
from app.orchestration.prompt_builder import build_prompt
from app.ingestion.pipeline import ingest_csv_to_chroma
from app.ingestion.ticket_loader import load_tickets_from_csv
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

app = FastAPI(title="supportFAQagent API", version="1.0")

# --- Configuração ---
def load_config(domain="suporte-vps"):
    config_path = os.path.join("domains", domain, "domain.yaml")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}

config = load_config()

# --- Instanciação Global ---
persist_directory = os.path.join("data", "chroma")
embeddings = get_embeddings(
    provider=config.get("embedding", {}).get("provider", "openai"),
    model=config.get("embedding", {}).get("model", "text-embedding-3-small")
)
chroma_store = ChromaStore(persist_directory=persist_directory, embedding_function=embeddings)

llm = LLMWrapper(
    provider=config.get("llm", {}).get("provider", "openai"),
    model=config.get("llm", {}).get("model", "gpt-4o-mini")
)

# --- Modelos Pydantic ---
class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    session_id: str
    message: str
    history: Optional[List[Message]] = []

class IngestRequest(BaseModel):
    title: str
    content: str

class CsvIngestRequest(BaseModel):
    filepath: str

# --- Endpoints ---
@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    # 1. Busca documentos similares no Chroma
    top_k = config.get("rag", {}).get("top_k", 5)
    results = chroma_store.similarity_search_with_score(request.message, top_k=top_k)
    
    chunks = [doc for doc, score in results]
    
    # 2. Monta o prompt
    # history expects dict, we convert from pydantic Message
    history_dicts = [{"role": msg.role, "content": msg.content} for msg in request.history]
    prompt = build_prompt(request.message, chunks, history=history_dicts)
    
    # 3. Chama o LLM
    try:
        response_text = await llm.complete(prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    # Exemplo simples de confiança: no MVP podemos apenas considerar falso. 
    # Em um sistema real, poderíamos avaliar a resposta ou score de busca.
    escalated = False
    if "não sei" in response_text.lower() or "escalar para um humano" in response_text.lower():
        escalated = True

    return {
        "answer": response_text,
        "escalated": escalated,
        "confidence": 0.9 if not escalated else 0.1 # Placeholder score
    }

@app.post("/ingest")
async def ingest_endpoint(request: IngestRequest):
    """
    Ingestão de um único chamado via webhook (ex: n8n)
    """
    content = f"Título: {request.title}\n\n{request.content}"
    doc = Document(page_content=content, metadata={"source": "api"})
    
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150
    )
    chunks = text_splitter.split_documents([doc])
    chroma_store.add_documents(chunks)
    
    return {"message": "Documento ingerido com sucesso", "chunks": len(chunks)}

@app.post("/ingest_csv")
async def ingest_csv_endpoint(request: CsvIngestRequest):
    """
    Endpoint utilitário para ingerir um CSV completo (para treinos batch)
    """
    if not os.path.exists(request.filepath):
        raise HTTPException(status_code=404, detail="Arquivo CSV não encontrado.")
    
    num_chunks = ingest_csv_to_chroma(request.filepath, chroma_store)
    return {"message": f"CSV ingerido com sucesso. {num_chunks} chunks criados."}

@app.post("/feedback")
async def feedback_endpoint(message_id: str, helpful: bool):
    """
    Endpoint para feedback pós atendimento (Pós-MVP)
    """
    return {"message": "Feedback recebido", "message_id": message_id, "helpful": helpful}
