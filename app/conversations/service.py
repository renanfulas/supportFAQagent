from __future__ import annotations

import hashlib
import hmac
import logging

from app.conversations.repository import ConversationRepository
from app.core.errors import DatabaseUnavailableError
from app.core.logging import log_event
from app.db.runtime import DatabaseRuntime


logger = logging.getLogger(__name__)


class ConversationHistoryService:
    def __init__(
        self,
        runtime: DatabaseRuntime,
        *,
        repository: ConversationRepository | None = None,
    ) -> None:
        self.runtime = runtime
        self.repository = repository or ConversationRepository(runtime)

    def load_recent(
        self,
        *,
        domain: str,
        channel: str,
        session_id: str | None,
        request_id: str | None,
        customer_id: str | None = None,
    ) -> list[dict[str, str]]:
        limit = self.runtime.settings.conversation_history_messages
        if (
            not self.runtime.persistence_enabled
            or (not session_id and not customer_id)
            or limit <= 0
        ):
            return []
        try:
            session_hash = (
                hash_session(
                    session_id,
                    self.runtime.settings.persistence_hash_secret or "",
                )
                if session_id
                else None
            )
            return self.repository.load_recent(
                domain=domain,
                channel=channel,
                session_hash=session_hash,
                session_hash_version=self.runtime.settings.persistence_hash_version,
                customer_id=customer_id,
                limit=limit,
            )
        except DatabaseUnavailableError:
            log_event(
                logger,
                "conversation_history_unavailable",
                request_id=request_id,
                domain=domain,
                channel=channel,
                error_code="database_unavailable",
            )
            return []


def hash_session(value: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        value.strip().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
