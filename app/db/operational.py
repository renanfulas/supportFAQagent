from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.api.schemas.feedback import FeedbackRequest, FeedbackResponse
from app.core.errors import DatabaseUnavailableError
from app.core.persistence_sanitize import (
    REDACTION_VERSION,
    sanitize_for_persistence,
    sanitize_payload,
)
from app.db.runtime import DatabaseRuntime


HANDOFF_NOT_REQUIRED = "handoff_not_required"
HANDOFF_QUEUED = "handoff_queued"
HANDOFF_UNAVAILABLE = "handoff_unavailable"


@dataclass(frozen=True)
class ChatAuditInput:
    request_id: str
    domain: str
    session_id: str | None
    question: str
    answer: str
    confidence: float
    escalated: bool
    handoff_reasons: list[str]
    references: list[str]
    error_code: str | None


class OperationalRepository:
    def __init__(self, runtime: DatabaseRuntime) -> None:
        self.runtime = runtime

    def record_chat(self, audit: ChatAuditInput) -> str:
        if not self.runtime.enabled:
            return HANDOFF_UNAVAILABLE if audit.escalated else HANDOFF_NOT_REQUIRED

        question = sanitize_for_persistence(audit.question)
        answer = sanitize_for_persistence(audit.answer)
        payload = sanitize_payload(
            {
                "request_id": audit.request_id,
                "domain": audit.domain,
                "handoff_reasons": audit.handoff_reasons,
                "references": audit.references,
                "error_code": audit.error_code,
                "summary": question[:500] if question else "",
            }
        )
        try:
            with self.runtime.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT id FROM domains WHERE name = %s LIMIT 1",
                        (audit.domain,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise DatabaseUnavailableError("domain is not persisted")
                    cursor.execute(
                        """
                        INSERT INTO chat_audits (
                          request_id, domain_id, session_hash, question_sanitized,
                          answer_sanitized, confidence, escalated, handoff_reasons,
                          message_references, error_code, redaction_version
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
                        ON CONFLICT (request_id) DO NOTHING
                        """,
                        (
                            audit.request_id,
                            row[0],
                            self._hash(audit.session_id),
                            question,
                            answer,
                            audit.confidence,
                            audit.escalated,
                            json.dumps(audit.handoff_reasons),
                            json.dumps(audit.references),
                            audit.error_code,
                            REDACTION_VERSION,
                        ),
                    )
                    if audit.escalated:
                        cursor.execute(
                            """
                            INSERT INTO operational_outbox (
                              event_type, idempotency_key, request_id, payload_sanitized
                            )
                            VALUES ('handoff.requested', %s, %s, %s::jsonb)
                            ON CONFLICT (idempotency_key) DO NOTHING
                            """,
                            (
                                f"handoff:{audit.request_id}",
                                audit.request_id,
                                json.dumps(payload),
                            ),
                        )
            return HANDOFF_QUEUED if audit.escalated else HANDOFF_NOT_REQUIRED
        except Exception:
            return HANDOFF_UNAVAILABLE if audit.escalated else HANDOFF_NOT_REQUIRED

    def record_feedback(self, feedback: FeedbackRequest) -> FeedbackResponse:
        if not self.runtime.enabled:
            return FeedbackResponse(
                feedback_id=str(uuid4()),
                accepted=True,
                status="accepted",
                storage="pending_persistence",
            )

        feedback_id = str(uuid4())
        try:
            comment = sanitize_for_persistence(feedback.comment)
        except Exception as exc:
            raise DatabaseUnavailableError("feedback sanitization failed") from exc
        try:
            with self.runtime.transaction() as connection:
                with connection.cursor() as cursor:
                    audit = None
                    if feedback.request_id:
                        cursor.execute(
                            """
                            SELECT id, escalated, handoff_reasons, message_references, error_code
                            FROM chat_audits WHERE request_id = %s
                            """,
                            (feedback.request_id,),
                        )
                        audit = cursor.fetchone()
                    context_status = "matched" if audit else "orphan"
                    mismatch = bool(
                        audit
                        and (
                            (feedback.escalated is not None and feedback.escalated != audit[1])
                            or (feedback.handoff_reasons and feedback.handoff_reasons != audit[2])
                            or (feedback.references and feedback.references != audit[3])
                            or (feedback.error_code and feedback.error_code != audit[4])
                        )
                    )
                    cursor.execute(
                        """
                        INSERT INTO feedback (
                          id, request_id, chat_audit_id, session_hash, helpful, reason,
                          comment_sanitized, source, context_status, context_mismatch,
                          redaction_version
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            feedback_id,
                            feedback.request_id,
                            audit[0] if audit else None,
                            self._hash(feedback.session_id),
                            feedback.helpful,
                            sanitize_for_persistence(feedback.reason),
                            comment,
                            feedback.source,
                            context_status,
                            mismatch,
                            REDACTION_VERSION,
                        ),
                    )
        except DatabaseUnavailableError:
            raise
        return FeedbackResponse(
            feedback_id=feedback_id,
            accepted=True,
            status=context_status,
            storage="postgres",
        )

    def _hash(self, value: str | None) -> str | None:
        if not value:
            return None
        secret = self.runtime.settings.persistence_hash_secret or ""
        return hmac.new(secret.encode(), value.strip().encode(), hashlib.sha256).hexdigest()
