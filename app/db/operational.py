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
from app.notifications.support_team import render_support_team_notifications
from app.support.transcript import build_support_snapshot_context


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
    customer_id: str | None = None
    # WS-3: whether this turn needs a human in the queue. None keeps the legacy
    # behavior (enqueue == escalated); a bool decouples the queue from escalated so a
    # low_confidence-only turn can stay escalated/logged without flooding the queue.
    requires_human_queue: bool | None = None
    turn_id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def human_queue_required(self) -> bool:
        """Whether to enqueue a human handoff for this turn (falls back to escalated)."""
        if self.requires_human_queue is None:
            return self.escalated
        return self.requires_human_queue


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
                    HANDOFF_UNAVAILABLE if audit.human_queue_required else HANDOFF_NOT_REQUIRED
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
                    conversation_id = None
                    if session_hash:
                        persisted_conversation = self.conversations.append_turn(
                            cursor=cursor,
                            domain_id=row[0],
                            session_hash=session_hash,
                            session_hash_version=session_hash_version or "",
                            channel=audit.channel,
                            customer_id=audit.customer_id,
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
                        conversation_id = persisted_conversation.conversation_id
                    if getattr(
                        self.runtime.settings, "enable_conversation_archive", False
                    ):
                        self._enqueue_conversation_archive(
                            cursor=cursor,
                            turn_id=str(persisted_turn_id),
                            request_id=safe_request_id,
                            audit=audit,
                            session_hash=session_hash,
                            session_hash_version=session_hash_version,
                            question=question,
                            answer=answer,
                            handoff_reasons=handoff_reasons,
                            references=references,
                            error_code=error_code,
                        )
                    handoff_status = HANDOFF_NOT_REQUIRED
                    if audit.human_queue_required:
                        support_case_id, organized_context = (
                            self._upsert_support_case(
                                cursor=cursor,
                                domain_id=row[0],
                                customer_id=audit.customer_id,
                                conversation_id=conversation_id,
                                turn_id=str(persisted_turn_id),
                                request_id=safe_request_id,
                                channel=audit.channel,
                                handoff_reasons=handoff_reasons,
                                references=references,
                                error_code=error_code,
                                summary=question[:500],
                            )
                        )
                        payload = {
                            **payload,
                            "support_case_id": support_case_id,
                        }
                        # Push carries the same bounded context the read surface
                        # serves, so both describe the handoff identically. The
                        # block is already sanitized inside the snapshot build.
                        if organized_context is not None:
                            payload["organized_context"] = organized_context
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
                        self._enqueue_support_team_notifications(
                            cursor=cursor,
                            turn_id=str(persisted_turn_id),
                            support_case_id=support_case_id,
                            request_id=safe_request_id,
                            domain=audit.domain,
                            handoff_reasons=handoff_reasons,
                            summary=question[:500],
                            references=references,
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
                    HANDOFF_UNAVAILABLE if audit.human_queue_required else HANDOFF_NOT_REQUIRED
                ),
                persistence_status=PERSISTENCE_UNAVAILABLE,
                turn_id=audit.turn_id,
            )

    def _enqueue_conversation_archive(
        self,
        *,
        cursor,
        turn_id: str,
        request_id: str,
        audit: ChatAuditInput,
        session_hash: str | None,
        session_hash_version: str | None,
        question: str,
        answer: str,
        handoff_reasons: list[str],
        references: list[str],
        error_code: str | None,
    ) -> None:
        """Enqueue an append-only copy of the persisted turn.

        Runs inside the same transaction as the turn write, so the insurance
        copy shares the source-of-truth durability guarantee. The dispatcher
        drains it to the off-box sink off the hot path.
        """
        archive_payload = sanitize_payload(
            {
                "turn_id": turn_id,
                "request_id": request_id,
                "domain": audit.domain,
                "channel": audit.channel,
                "session_hash": session_hash,
                "session_hash_version": session_hash_version,
                "customer_id": audit.customer_id,
                "confidence": audit.confidence,
                "escalated": audit.escalated,
                "handoff_reasons": handoff_reasons,
                "references": references,
                "error_code": error_code,
                "question_sanitized": question,
                "answer_sanitized": answer,
                "redaction_version": REDACTION_VERSION,
            }
        )
        cursor.execute(
            """
            INSERT INTO operational_outbox (
              event_type, idempotency_key, request_id, payload_sanitized
            )
            VALUES ('conversation.turn.archived', %s, %s, %s::jsonb)
            ON CONFLICT (idempotency_key)
            DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
            """,
            (
                f"archive:{turn_id}",
                request_id,
                json.dumps(archive_payload),
            ),
        )

    def _upsert_support_case(
        self,
        *,
        cursor,
        domain_id,
        customer_id: str | None,
        conversation_id: str | None,
        turn_id: str,
        request_id: str,
        channel: str,
        handoff_reasons: list[str],
        references: list[str],
        error_code: str | None,
        summary: str,
    ) -> tuple[str, dict | None]:
        snapshot: dict = {
            "request_id": request_id,
            "channel": channel,
            "handoff_reasons": handoff_reasons,
            "references": references,
            "error_code": error_code,
            "summary": summary,
        }
        # Best-effort enrichment: the ticket and its handoff event must survive
        # even if assembling the bounded conversation context fails, so the
        # "unresolved turn -> durable ticket" guarantee never weakens.
        try:
            snapshot["organized_context"] = build_support_snapshot_context(
                cursor, conversation_id
            )
        except Exception as exc:  # noqa: BLE001 - degrade, never drop the ticket
            log_event(
                logger,
                "support_snapshot_context_unavailable",
                request_id=request_id,
                error_type=type(exc).__name__,
            )
        context_snapshot = sanitize_payload(snapshot)
        cursor.execute(
            """
            INSERT INTO support_cases (
              domain_id, customer_id, conversation_id, request_id, channel,
              reason_codes, context_snapshot_sanitized, idempotency_key
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
            ON CONFLICT (idempotency_key)
            DO UPDATE SET
              updated_at = now(),
              context_snapshot_sanitized = EXCLUDED.context_snapshot_sanitized
            RETURNING id
            """,
            (
                domain_id,
                customer_id,
                conversation_id,
                request_id,
                channel,
                json.dumps(handoff_reasons),
                json.dumps(context_snapshot),
                f"support_case:{turn_id}",
            ),
        )
        return str(cursor.fetchone()[0]), context_snapshot.get("organized_context")

    def _enqueue_support_team_notifications(
        self,
        *,
        cursor,
        turn_id: str,
        support_case_id: str,
        request_id: str,
        domain: str,
        handoff_reasons: list[str],
        summary: str,
        references: list[str],
    ) -> None:
        """Fan a handoff out to internal WhatsApp recipients, one event each.

        Dark by default: only runs when ``ENABLE_SUPPORT_TEAM_WHATSAPP_NOTIFY`` is
        on and recipients are configured. Each ``whatsapp.message.requested`` event
        is idempotent per turn + recipient, so a retried turn never double-alerts.

        Rendering is best-effort so the durable ticket and its ``handoff.requested``
        event never depend on it. The recipient ``to`` is written verbatim (not via
        ``sanitize_payload``, which would redact the phone number) so the dispatcher
        can deliver it; ``text`` is built from already-sanitized snapshot fields.
        """

        settings = self.runtime.settings
        if not getattr(settings, "enable_support_team_whatsapp_notify", False):
            return
        recipients = list(
            getattr(settings, "support_team_whatsapp_recipient_list", []) or []
        )
        if not recipients:
            return
        try:
            notifications = render_support_team_notifications(
                turn_id=turn_id,
                support_case_id=support_case_id,
                domain=domain,
                handoff_reasons=handoff_reasons,
                summary=summary,
                references=references,
                recipients=recipients,
            )
        except Exception as exc:  # noqa: BLE001 - degrade, never drop the ticket
            log_event(
                logger,
                "support_team_notify_render_unavailable",
                request_id=request_id,
                error_type=type(exc).__name__,
            )
            return
        for notification in notifications:
            cursor.execute(
                """
                INSERT INTO operational_outbox (
                  event_type, idempotency_key, request_id, payload_sanitized
                )
                VALUES ('whatsapp.message.requested', %s, %s, %s::jsonb)
                ON CONFLICT (idempotency_key)
                DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
                """,
                (
                    notification.idempotency_key,
                    request_id,
                    json.dumps(
                        {
                            "to": notification.to,
                            "text": notification.text,
                            "support_case_id": support_case_id,
                            "request_id": request_id,
                        }
                    ),
                ),
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
