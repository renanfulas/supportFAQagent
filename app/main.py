from fastapi import FastAPI

from app.api.routes import chat, domains, feedback, health, ingestion
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="API para agentes de atendimento por dominio com RAG.",
    )

    application.include_router(health.router)
    application.include_router(domains.router, prefix="/domains", tags=["domains"])
    application.include_router(ingestion.router, prefix="/ingestion", tags=["ingestion"])
    application.include_router(chat.router, prefix="/chat", tags=["chat"])
    application.include_router(feedback.router, prefix="/feedback", tags=["feedback"])
    return application


app = create_app()
