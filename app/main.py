from fastapi import FastAPI

from app.api.routes import chat, domains, health, ingestion
from app.core.config import get_settings


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="API para agentes de atendimento por dominio com RAG.",
)

app.include_router(health.router)
app.include_router(domains.router, prefix="/domains", tags=["domains"])
app.include_router(ingestion.router, prefix="/ingestion", tags=["ingestion"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
