from dataclasses import dataclass

from app.core.config import Settings
from app.web_auth.delivery import InMemoryOtpDeliveryAdapter
from app.web_auth.service import WebWhatsAppAuthService
from app.web_auth.storage import InMemoryWebAuthStore
from app.web_auth.storage import PostgresWebAuthStore
from app.db.runtime import DatabaseRuntime


@dataclass(frozen=True)
class WebAuthRuntime:
    service: WebWhatsAppAuthService
    delivery: InMemoryOtpDeliveryAdapter


def create_web_auth_runtime(
    settings: Settings,
    database_runtime: DatabaseRuntime | None = None,
) -> WebAuthRuntime:
    store = (
        PostgresWebAuthStore(database_runtime)
        if settings.web_auth_storage_backend == "postgres" and database_runtime is not None
        else InMemoryWebAuthStore()
    )
    delivery = InMemoryOtpDeliveryAdapter()
    return WebAuthRuntime(
        service=WebWhatsAppAuthService(
            settings=settings,
            store=store,
            delivery=delivery,
        ),
        delivery=delivery,
    )
