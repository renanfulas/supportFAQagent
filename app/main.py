import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import chat, domains, feedback, health, ingestion
from app.core.config import get_settings
from app.core.logging import configure_logging, log_event
from app.core.request_context import (
    REQUEST_ID_HEADER,
    get_request_id,
    resolve_request_id,
)


logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="API para agentes de atendimento por dominio com RAG.",
    )

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        log_event(
            logger,
            "http_request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        )
        return response

    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        request_id = get_request_id(request)
        log_event(
            logger,
            "http_error",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=exc.status_code,
            detail=exc.detail,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "request_id": request_id},
            headers={REQUEST_ID_HEADER: request_id},
        )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        request_id = get_request_id(request)
        log_event(
            logger,
            "validation_error",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=422,
        )
        return JSONResponse(
            status_code=422,
            content={
                "detail": jsonable_encoder(exc.errors()),
                "request_id": request_id,
            },
            headers={REQUEST_ID_HEADER: request_id},
        )

    application.include_router(health.router)
    application.include_router(domains.router, prefix="/domains", tags=["domains"])
    application.include_router(ingestion.router, prefix="/ingestion", tags=["ingestion"])
    application.include_router(chat.router, prefix="/chat", tags=["chat"])
    application.include_router(feedback.router, prefix="/feedback", tags=["feedback"])
    return application


app = create_app()
