from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field
from uuid import uuid4

from app.api.schemas.feedback import (
    FeedbackRequest,
    FeedbackResponse,
    safe_feedback_identifier,
    safe_feedback_source,
)
from app.core.errors import DatabaseUnavailableError
from app.core.logging import log_event
from app.core.persistence_sanitize import (
    REDACTION_VERSION,
    sanitize_for_persistence,
    sanitize_payload,
)
from app.db.runtime import DatabaseRuntime
from app.conversations.repository import ConversationRepository
from app.conversations.service import hash_session


logger = logging.getLogger(__name__)

HANDOFF_NOT_REQUIRED = "handoff_not_required"
HANDOFF_QUEUED = "handoff_queued"
HANDOFF_UNAVAILABLE = "handoff_unavailable"
PERSISTENCE_DISABLED = "persistence_disabled"
PERSISTENCE_PERSISTED = "persisted"
PERSISTENCE_UNAVAILABLE = "persistence_unavailable"


class FeedbackIntegrityConflictError(DatabaseUnavailableError):
    """Raised when an idempotency key is reused with a different payload."""


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
    channel: str = "api"
    turn_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True)
class ChatPersistenceResult:
    handoff_status: str
    persistence_status: str
    turn_id: str
    request_id_reused: bool = False


class OperationalRepository:
    def __init__(self, runtime: DatabaseRuntime) -> None:
        self.runtime = runtime
        self.conversations = ConversationRepository(runtime)

    def record_chat(self, audit: ChatAuditInput) -> ChatPersistenceResult:
        if not self.runtime.persistence_enabled:
            return ChatPersistenceResult(
                handoff_status=(
                    HANDOFF_UNAVAILABLE if audit.escalated else HANDOFF_NOT_REQUIRED
                ),
                persistence_status=PERSISTENCE_DISABLED,
                turn_id=audit.turn_id,
            )

        safe_request_id = None
        try:
            safe_request_id = safe_feedback_identifier(
                audit.request_id,
                field_name="request_id",
            )
            if safe_request_id is None:
                raise ValueError("chat request_id is required")
            question = self._sanitize_required(audit.question)
            answer = self._sanitize_required(audit.answer)
            handoff_reasons = self._sanitize_string_list(audit.handoff_reasons)
            references = self._sanitize_string_list(audit.references)
            error_code = sanitize_for_persistence(audit.error_code)
            session_hash = self._hash(audit.session_id)
            session_hash_version = self._hash_version(session_hash)
            request_fingerprint = self._request_fingerprint(
                audit=audit,
                session_hash=session_hash,
            )
            payload = sanitize_payload(
                {
                    "request_id": safe_request_id,
                    "domain": audit.domain,
                    "handoff_reasons": handoff_reasons,
                    "references": references,
                    "error_code": error_code,
                    "summary": question[:500],
                }
            )
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
                        SELECT EXISTS (
                          SELECT 1 FROM chat_audits
                          WHERE request_id = %s
                            AND request_fingerprint IS DISTINCT FROM %s
                        )
                        """,
                            (safe_request_id, request_fingerprint),
                    )
                    request_id_reused = bool(cursor.fetchone()[0])
                    cursor.execute(
                        """
                        INSERT INTO chat_audits (
                          turn_id, request_id, request_fingerprint, domain_id,
                          channel, session_hash, session_hash_version, question_sanitized,
                          answer_sanitized, confidence, escalated, handoff_reasons,
                          message_references, error_code, redaction_version
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
                        ON CONFLICT (request_id, request_fingerprint)
                          WHERE request_fingerprint IS NOT NULL
                        DO UPDATE SET request_id = EXCLUDED.request_id
                        RETURNING id, turn_id
                        """,
                        (
                            audit.turn_id,
                            safe_request_id,
                            request_fingerprint,
                            row[0],
                            audit.channel,
                            session_hash,
                            session_hash_version,
                            question,
                            answer,
                            audit.confidence,
                            audit.escalated,
                            json.dumps(handoff_reasons),
                            json.dumps(references),
                            error_code,
                            REDACTION_VERSION,
                        ),
                    )
                    audit_id, persisted_turn_id = cursor.fetchone()
                    if session_hash:
                        self.conversations.append_turn(
                            cursor=cursor,
                            domain_id=row[0],
                            session_hash=session_hash,
                            session_hash_version=session_hash_version or "",
                            channel=audit.channel,
                            audit_id=audit_id,
                            turn_id=str(persisted_turn_id),
                            request_id=safe_request_id,
                            question_sanitized=question,
                            answer_sanitized=answer,
                            confidence=audit.confidence,
                            escalated=audit.escalated,
                            handoff_reasons=handoff_reasons,
                            references=references,
                            error_code=error_code,
                        )
                    handoff_status = HANDOFF_NOT_REQUIRED
                    if audit.escalated:
                        cursor.execute(
                            """
                            INSERT INTO operational_outbox (
                              event_type, idempotency_key, request_id, payload_sanitized
                            )
                            VALUES ('handoff.requested', %s, %s, %s::jsonb)
                            ON CONFLICT (idempotency_key)
                            DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
                            RETURNING status
                            """,
                            (
                                f"handoff:{persisted_turn_id}",
                                safe_request_id,
                                json.dumps(payload),
                            ),
                        )
                        outbox_row = cursor.fetchone()
                        handoff_status = (
                            HANDOFF_QUEUED
                            if outbox_row is not None and outbox_row[0] != "dead_letter"
                            else HANDOFF_UNAVAILABLE
                        )
            return ChatPersistenceResult(
                handoff_status=handoff_status,
                persistence_status=PERSISTENCE_PERSISTED,
                turn_id=str(persisted_turn_id),
                request_id_reused=request_id_reused,
            )
        except Exception as exc:
            log_event(
                logger,
                "chat_persistence_unavailable",
                request_id=safe_request_id,
                domain=sanitize_for_persistence(audit.domain),
                channel=sanitize_for_persistence(audit.channel),
                escalated=audit.escalated,
                error_type=type(exc).__name__,
                error_code="persistence_unavailable",
            )
            return ChatPersistenceResult(
                handoff_status=(
                    HANDOFF_UNAVAILABLE if audit.escalated else HANDOFF_NOT_REQUIRED
                ),
                persistence_status=PERSISTENCE_UNAVAILABLE,
                turn_id=audit.turn_id,
            )

    def record_feedback(self, feedback: FeedbackRequest) -> FeedbackResponse:
        if not self.runtime.persistence_enabled:
            return FeedbackResponse(
                feedback_id=str(uuid4()),
                accepted=True,
                status="accepted",
                storage="pending_persistence",
            )

        try:
            request_id = safe_feedback_identifier(
                feedback.request_id,
                field_name="request_id",
            )
            message_id = safe_feedback_identifier(
                feedback.message_id,
                field_name="message_id",
            )
            comment = sanitize_for_persistence(feedback.comment)
            reason = sanitize_for_persistence(feedback.reason)
            handoff_reasons = self._sanitize_string_list(feedback.handoff_reasons)
            references = self._sanitize_string_list(feedback.references)
            error_code = sanitize_for_persistence(feedback.error_code)
            session_hash = self._hash(feedback.session_id)
            session_hash_version = self._hash_version(session_hash)
            source = safe_feedback_source(feedback.source)
            idempotency_key = self._feedback_idempotency_key(
                message_id=message_id,
                request_id=request_id,
                source=source,
            )
            feedback_fingerprint = self._feedback_fingerprint(
                request_id=request_id,
                message_id=message_id,
                session_hash=session_hash,
                session_hash_version=session_hash_version,
                helpful=feedback.helpful,
                reason=reason,
                comment=comment,
                source=source,
                escalated=feedback.escalated,
                handoff_reasons=handoff_reasons,
                references=references,
                error_code=error_code,
            )
        except Exception as exc:
            raise DatabaseUnavailableError("feedback sanitization failed") from exc
        try:
            with self.runtime.transaction() as connection:
                with connection.cursor() as cursor:
                    audit = None
                    if request_id:
                        audit = self._find_feedback_audit(
                            cursor=cursor,
                            request_id=request_id,
                            session_hash=session_hash,
                            session_hash_version=session_hash_version,
                        )
                    context_status = "matched" if audit else "orphan"
                    mismatch = bool(
                        audit
                        and (
                            (feedback.escalated is not None and feedback.escalated != audit[1])
                            or (handoff_reasons and handoff_reasons != audit[2])
                            or (references and references != audit[3])
                            or (error_code and error_code != audit[4])
                        )
                    )
                    cursor.execute(
                        """
                        INSERT INTO feedback (
                          request_id, message_id, chat_audit_id, session_hash,
                          session_hash_version, helpful, reason,
                          comment_sanitized, source, context_status, context_mismatch,
                          redaction_version, idempotency_key, feedback_fingerprint
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (idempotency_key)
                          WHERE idempotency_key IS NOT NULL
                        DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
                        RETURNING id, context_status, feedback_fingerprint
                        """,
                        (
                            request_id,
                            message_id,
                            audit[0] if audit else None,
                            session_hash,
                            session_hash_version,
                            feedback.helpful,
                            reason,
                            comment,
                            source,
                            context_status,
                            mismatch,
                            REDACTION_VERSION,
                            idempotency_key,
                            feedback_fingerprint,
                        ),
                    )
                    persisted_feedback = cursor.fetchone()
                    if persisted_feedback is None:
                        raise DatabaseUnavailableError("feedback insert returned no row")
                    feedback_id, persisted_status, persisted_fingerprint = persisted_feedback
                    if persisted_fingerprint != feedback_fingerprint:
                        raise FeedbackIntegrityConflictError(
                            "feedback idempotency key reused with different payload"
                        )
                    context_status = str(persisted_status)
        except FeedbackIntegrityConflictError:
            raise
        except DatabaseUnavailableError:
            raise
        return FeedbackResponse(
            feedback_id=str(feedback_id),
            accepted=True,
            status=context_status,
            storage="postgres",
        )

    def _find_feedback_audit(
        self,
        *,
        cursor,
        request_id: str,
        session_hash: str | None,
        session_hash_version: str | None,
    ):
        if session_hash:
            cursor.execute(
                """
                SELECT id, escalated, handoff_reasons, message_references, error_code
                FROM chat_audits candidate
                WHERE candidate.request_id = %s
                  AND candidate.session_hash = %s
                  AND candidate.session_hash_version = %s
                  AND NOT EXISTS (
                    SELECT 1
                    FROM chat_audits other
                    WHERE other.request_id = candidate.request_id
                      AND other.session_hash = candidate.session_hash
                      AND other.session_hash_version = candidate.session_hash_version
                      AND other.id <> candidate.id
                  )
                LIMIT 1
                """,
                (request_id, session_hash, session_hash_version),
            )
            return cursor.fetchone()

        cursor.execute(
            """
            SELECT id, escalated, handoff_reasons, message_references, error_code
            FROM chat_audits candidate
            WHERE candidate.request_id = %s
              AND NOT EXISTS (
                SELECT 1
                FROM chat_audits other
                WHERE other.request_id = candidate.request_id
                  AND other.id <> candidate.id
              )
            LIMIT 1
            """,
            (request_id,),
        )
        return cursor.fetchone()

    def _hash(self, value: str | None) -> str | None:
        if not value:
            return None
        return hash_session(
            value,
            self.runtime.settings.persistence_hash_secret or "",
        )

    def _hash_version(self, session_hash: str | None) -> str | None:
        if session_hash is None:
            return None
        return self.runtime.settings.persistence_hash_version

    def _sanitize_string_list(self, values: list[str]) -> list[str]:
        sanitized = sanitize_payload(values)
        if not isinstance(sanitized, list) or not all(
            isinstance(item, str) for item in sanitized
        ):
            raise TypeError("persisted metadata must be a list of strings")
        return sanitized

    def _sanitize_required(self, value: str) -> str:
        sanitized = sanitize_for_persistence(value)
        if sanitized is None:
            raise ValueError("required persisted content was empty after sanitization")
        return sanitized

    def _request_fingerprint(
        self,
        *,
        audit: ChatAuditInput,
        session_hash: str | None,
    ) -> str:
        value = json.dumps(
            {
                "domain": audit.domain,
                "channel": audit.channel,
                "session_hash": session_hash,
                "question": audit.question,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hmac.new(
            (self.runtime.settings.persistence_hash_secret or "").encode("utf-8"),
            value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _feedback_idempotency_key(
        self,
        *,
        message_id: str | None,
        request_id: str | None,
        source: str,
    ) -> str | None:
        if message_id is None:
            return None
        return self._stable_fingerprint(
            {
                "kind": "feedback-idempotency",
                "message_id": message_id,
                "request_id": request_id,
                "source": source,
            }
        )

    def _feedback_fingerprint(
        self,
        *,
        request_id: str | None,
        message_id: str | None,
        session_hash: str | None,
        session_hash_version: str | None,
        helpful: bool,
        reason: str | None,
        comment: str | None,
        source: str,
        escalated: bool | None,
        handoff_reasons: list[str],
        references: list[str],
        error_code: str | None,
    ) -> str:
        return self._stable_fingerprint(
            {
                "kind": "feedback-payload",
                "request_id": request_id,
                "message_id": message_id,
                "session_hash": session_hash,
                "session_hash_version": session_hash_version,
                "helpful": helpful,
                "reason": reason,
                "comment": comment,
                "source": source,
                "escalated": escalated,
                "handoff_reasons": handoff_reasons,
                "references": references,
                "error_code": error_code,
            }
        )

    def _stable_fingerprint(self, value: dict[str, object]) -> str:
        serialized = json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
