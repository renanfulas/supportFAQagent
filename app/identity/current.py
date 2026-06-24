from __future__ import annotations

from dataclasses import dataclass

from app.conversations.service import hash_session
from app.core.config import Settings
from app.web_auth.service import WebWhatsAppAuthService


@dataclass(frozen=True)
class CurrentIdentityContext:
    """Request-local identity context without exposing raw session identifiers."""

    authenticated: bool
    verified_identity_id: str | None
    customer_id: str | None
    phone_last4: str | None
    persistence_session_hash: str | None
    persistence_session_hash_version: str | None


class CurrentIdentityResolver:
    """Resolve the current session across Auth and persistence hash domains."""

    def __init__(
        self,
        *,
        settings: Settings,
        web_auth_service: WebWhatsAppAuthService | None = None,
    ) -> None:
        self.settings = settings
        self.web_auth_service = web_auth_service

    def resolve(self, session_id: str | None) -> CurrentIdentityContext:
        if not session_id:
            return CurrentIdentityContext(
                authenticated=False,
                verified_identity_id=None,
                customer_id=None,
                phone_last4=None,
                persistence_session_hash=None,
                persistence_session_hash_version=None,
            )

        identity = (
            self.web_auth_service.get_session_identity(session_id)
            if self.web_auth_service is not None
            else None
        )
        return CurrentIdentityContext(
            authenticated=identity is not None,
            verified_identity_id=identity.id if identity is not None else None,
            customer_id=identity.customer_id if identity is not None else None,
            phone_last4=identity.phone_last4 if identity is not None else None,
            persistence_session_hash=hash_session(
                session_id,
                self.settings.persistence_hash_secret or "",
            ),
            persistence_session_hash_version=self.settings.persistence_hash_version,
        )
