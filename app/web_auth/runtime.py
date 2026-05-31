from dataclasses import dataclass

from app.core.config import Settings
from app.web_auth.delivery import InMemoryOtpDeliveryAdapter
from app.web_auth.service import WebWhatsAppAuthService
from app.web_auth.storage import InMemoryWebAuthStore


@dataclass(frozen=True)
class WebAuthRuntime:
    service: WebWhatsAppAuthService
    delivery: InMemoryOtpDeliveryAdapter


def create_web_auth_runtime(settings: Settings) -> WebAuthRuntime:
    store = InMemoryWebAuthStore()
    delivery = InMemoryOtpDeliveryAdapter()
    return WebAuthRuntime(
        service=WebWhatsAppAuthService(
            settings=settings,
            store=store,
            delivery=delivery,
        ),
        delivery=delivery,
    )
