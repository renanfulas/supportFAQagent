import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import chat, domains, feedback, health, ingestion, web_auth, web_chat, zoom
from app.core.config import DEV_ENVS, get_settings
from app.core.logging import configure_logging, log_event
from app.core.rate_limit import InMemoryRateLimiter, RateLimitExceeded
from app.core.request_context import (
    REQUEST_ID_HEADER,
    get_request_id,
    resolve_request_id,
)
from app.core.web_session import extract_public_session_token
from app.web_auth.runtime import create_web_auth_runtime


logger = logging.getLogger(__name__)
CHAT_STATIC_DIR = Path(__file__).resolve().parent / "static" / "chat"


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    chat_rate_limiter = InMemoryRateLimiter(max_requests=settings.rate_limit_per_minute)
    web_chat_rate_limiter = InMemoryRateLimiter(
        max_requests=settings.web_chat_rate_limit_per_minute,
    )

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="API para agentes de atendimento por dominio com RAG.",
    )
    application.state.web_auth_runtime = create_web_auth_runtime(settings)

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id

        if request.url.path == "/chat" and settings.rate_limit_per_minute > 0:
            client_host = request.client.host if request.client else "unknown"
            rate_limit_key = f"{client_host}:{request.url.path}"
            try:
                chat_rate_limiter.check(rate_limit_key)
            except RateLimitExceeded as exc:
                log_event(
                    logger,
                    "rate_limit_exceeded",
                    request_id=request_id,
                    method=request.method,
                    path=request.url.path,
                    status_code=429,
                    client_host=client_host,
                    retry_after=exc.retry_after_seconds,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Too many requests",
                        "request_id": request_id,
                    },
                    headers={
                        REQUEST_ID_HEADER: request_id,
                        "Retry-After": str(exc.retry_after_seconds),
                    },
                )

        if request.url.path == "/web/chat" and settings.web_chat_rate_limit_per_minute > 0:
            client_host = request.client.host if request.client else "unknown"
            session_token = extract_public_session_token(
                request.cookies.get(settings.web_chat_session_cookie),
            )
            rate_limit_keys = [f"web:{client_host}:{request.url.path}"]
            if session_token:
                rate_limit_keys.append(f"web-session:{session_token}:{request.url.path}")

            try:
                for rate_limit_key in rate_limit_keys:
                    web_chat_rate_limiter.check(rate_limit_key)
            except RateLimitExceeded as exc:
                log_event(
                    logger,
                    "rate_limit_exceeded",
                    request_id=request_id,
                    method=request.method,
                    path=request.url.path,
                    status_code=429,
                    client_host=client_host,
                    retry_after=exc.retry_after_seconds,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Too many requests",
                        "request_id": request_id,
                    },
                    headers={
                        REQUEST_ID_HEADER: request_id,
                        "Retry-After": str(exc.retry_after_seconds),
                    },
                )

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
            headers={**(exc.headers or {}), REQUEST_ID_HEADER: request_id},
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

    @application.exception_handler(Exception)
    async def unexpected_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        request_id = get_request_id(request)
        log_event(
            logger,
            "unexpected_error",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=500,
            error_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error",
                "request_id": request_id,
            },
            headers={REQUEST_ID_HEADER: request_id},
        )

    chat_ui_enabled = (
        settings.app_env.lower() in DEV_ENVS
        or (settings.enable_chat_ui and settings.app_env.lower() != "production")
        or settings.enable_public_chat_ui
    )

    if chat_ui_enabled and CHAT_STATIC_DIR.exists():
        application.mount(
            "/chat-assets",
            StaticFiles(directory=CHAT_STATIC_DIR),
            name="chat-assets",
        )

        @application.get("/chat-ui", include_in_schema=False)
        @application.get("/chat-ui/", include_in_schema=False)
        def chat_ui() -> FileResponse:
            return FileResponse(CHAT_STATIC_DIR / "index.html")

    application.include_router(health.router)
    application.include_router(domains.router, prefix="/domains", tags=["domains"])
    application.include_router(ingestion.router, prefix="/ingestion", tags=["ingestion"])
    application.include_router(chat.router, prefix="/chat", tags=["chat"])
    application.include_router(feedback.router, prefix="/feedback", tags=["feedback"])
    application.include_router(web_chat.router, prefix="/web", tags=["web"])
    application.include_router(web_auth.router, prefix="/web/auth", tags=["web-auth"])
    application.include_router(zoom.router, prefix="/zoom", tags=["zoom"])
    return application


app = create_app()
