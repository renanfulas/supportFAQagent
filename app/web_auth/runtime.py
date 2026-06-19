from dataclasses import dataclass

from app.core.config import Settings
from app.integrations.hermes.client import HermesClient
from app.integrations.hermes.otp_delivery import HermesOtpDeliveryAdapter
from app.integrations.meta_whatsapp.client import MetaWhatsAppClient
from app.integrations.meta_whatsapp.otp_delivery import MetaWhatsAppOtpDeliveryAdapter
from app.web_auth.delivery import InMemoryOtpDeliveryAdapter
from app.web_auth.delivery import OtpDeliveryAdapter
from app.web_auth.service import WebWhatsAppAuthService
from app.web_auth.storage import InMemoryWebAuthStore
from app.web_auth.storage import PostgresWebAuthStore
from app.db.runtime import DatabaseRuntime


@dataclass(frozen=True)
class WebAuthRuntime:
    service: WebWhatsAppAuthService
    delivery: OtpDeliveryAdapter


def create_web_auth_runtime(
    settings: Settings,
    database_runtime: DatabaseRuntime | None = None,
) -> WebAuthRuntime:
    store = (
        PostgresWebAuthStore(database_runtime)
        if settings.web_auth_storage_backend == "postgres" and database_runtime is not None
        else InMemoryWebAuthStore()
    )
    delivery = _create_delivery_adapter(settings)
    return WebAuthRuntime(
        service=WebWhatsAppAuthService(
            settings=settings,
            store=store,
            delivery=delivery,
        ),
        delivery=delivery,
    )


def _create_delivery_adapter(settings: Settings) -> OtpDeliveryAdapter:
    if settings.enable_web_whatsapp_auth and settings.web_auth_otp_delivery_transport == "meta":
        return MetaWhatsAppOtpDeliveryAdapter(
            client=MetaWhatsAppClient(
                access_token=settings.meta_whatsapp_access_token or "",
                phone_number_id=settings.meta_whatsapp_phone_number_id or "",
                graph_api_version=settings.meta_whatsapp_graph_api_version,
                timeout_seconds=settings.meta_whatsapp_request_timeout_seconds,
            ),
            template_name=settings.meta_whatsapp_otp_template_name or "",
            language_code=settings.meta_whatsapp_otp_template_language,
        )
    if settings.enable_web_whatsapp_auth and settings.web_auth_otp_delivery_transport == "hermes":
        return HermesOtpDeliveryAdapter(
            client=HermesClient(
                base_url=settings.hermes_base_url or "",
                webhook_secret=settings.hermes_webhook_secret or "",
                timeout_seconds=settings.hermes_request_timeout_seconds,
                otp_delivery_path=settings.hermes_otp_delivery_path,
            ),
            template_name=settings.meta_whatsapp_otp_template_name or "web_login_otp",
        )
    return InMemoryOtpDeliveryAdapter()
