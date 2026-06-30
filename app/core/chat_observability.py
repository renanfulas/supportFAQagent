"""Shared emission of the ``chat_completed`` structured log event.

Every channel that calls ``ChatFlowService.answer`` must emit the same
per-turn observability event so funnel metrics ("por dominio") stay available
regardless of transport (web, API, Meta WhatsApp, Hermes WhatsApp, zoom).

The web and API routes assemble these fields inline; this helper exists so the
transports outside ``app/api/routes`` do not drift from the documented field set
in ``docs/observability.md`` or leak raw PII/session ids. Privacy rules: the
external session identifier is only ever logged as ``session_id_hash``.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from app.core.config import Settings
from app.core.logging import log_event
from app.core.privacy import hash_sensitive_value


def log_chat_completed(
    logger: logging.Logger,
    *,
    request_id: str,
    session_id: str,
    channel: str,
    response: Mapping[str, Any],
    handoff_status: str,
    persistence_status: str,
    request_id_reused: bool,
    settings: Settings,
    event: str = "chat_completed",
) -> None:
    """Emit ``chat_completed`` with the sanitized field set used by the web channels.

    Only call this on the answering turn (after ``ChatFlowService.answer``). Router
    menu/selection turns never call ``answer`` and must stay out of this event.
    """

    observability = response.get("observability", {})
    observability_fields = observability if isinstance(observability, dict) else {}
    references = response.get("references", [])
    references_count = len(references) if isinstance(references, list) else 0
    log_event(
        logger,
        event,
        request_id=request_id,
        domain=response.get("domain"),
        session_id_hash=hash_sensitive_value(
            session_id,
            secret=settings.persistence_hash_secret,
        ),
        confidence=response.get("confidence"),
        escalated=response.get("escalated"),
        handoff_reasons=response.get("handoff_reasons"),
        error_code=response.get("error_code"),
        provider_failure_kind=response.get("provider_failure_kind"),
        handoff_status=handoff_status,
        persistence_status=persistence_status,
        request_id_reused=request_id_reused,
        channel=channel,
        retrieval_backend=settings.retrieval_backend,
        references_count=references_count,
        total_ms=observability_fields.get("total_ms"),
        retrieval_ms=observability_fields.get("retrieval_ms"),
        llm_ms=observability_fields.get("llm_ms"),
    )
