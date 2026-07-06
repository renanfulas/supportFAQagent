from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.api.schemas.feedback import (
    FeedbackRequest,
    FeedbackResponse,
    safe_feedback_identifier,
    safe_feedback_source,
)
from app.core.errors import DatabaseUnavailableError, TransactionBusinessError
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
from app.support.wa_binding import build_support_deep_link


logger = logging.getLogger(__name__)

HANDOFF_NOT_REQUIRED = "handoff_not_required"
HANDOFF_QUEUED = "handoff_queued"
HANDOFF_UNAVAILABLE = "handoff_unavailable"
# Sprint 4b: the support_case was created, but the team was NOT notified yet —
# it is waiting on the web chat customer to confirm LGPD consent (OTP + name/
# email) via POST /web/handoff/consent before any outbound contact happens.
HANDOFF_PENDING_CONSENT = "handoff_pending_consent"
SUPPORT_CASE_STATUS_OPEN = "open"
SUPPORT_CASE_STATUS_PENDING_CONSENT = "pending_consent"
PERSISTENCE_DISABLED = "persistence_disabled"
PERSISTENCE_PERSISTED = "persisted"
PERSISTENCE_UNAVAILABLE = "persistence_unavailable"


class FeedbackIntegrityConflictError(DatabaseUnavailableError):
    """Raised when an idempotency key is reused with a different payload."""


class ConsentCaseNotFound(TransactionBusinessError):
    """No pending web-chat support_case matches request_id for this identity.

    Deliberately raised both when the case truly does not exist and when it
    belongs to a different customer_id -- the caller must not be able to tell
    the two apart (see promote_pending_consent's ownership check). Some of
    these raises happen inside ``with self.runtime.transaction()``, so this
    must subclass TransactionBusinessError to survive that wrapper unchanged
    instead of being reported as DatabaseUnavailableError.
    """


class InvalidConsentContact(Exception):
    """name/email supplied to POST /web/handoff/consent failed validation."""


_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _load_json_field(value: Any, *, default: Any) -> Any:
    """JSONB columns may arrive parsed (psycopg default) or as text."""

    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return default
    return default


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
    # Ponte WhatsApp<->console: "continuar no WhatsApp" -- so preenchido
    # quando o caso ja esta 'open' (nao 'pending_consent') e a frente esta
    # configurada. None em qualquer outro caso; o chamador so exibe o CTA
    # quando presente.
    support_deep_link: str | None = None


@dataclass(frozen=True)
class ConsentPromotionResult:
    support_case_id: str
    status: str
    opened_at: Any
    summary: str | None
    domain: str
    already_promoted: bool = False
    # Effective display name on the customer record after promotion (an earlier
    # consent wins over a retyped one), so the widget can mirror to the client
    # exactly what the team was told. None on the idempotent replay path.
    customer_name: str | None = None
    # Ponte WhatsApp<->console: "continuar no WhatsApp" -- only set the first
    # time a pending_consent case is promoted to open (already_promoted=True
    # replays don't need a fresh CTA).
    support_deep_link: str | None = None


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
                    support_deep_link: str | None = None
                    if audit.human_queue_required:
                        # Sprint 4b: the LGPD consent gate only applies to the web chat
                        # channel — WhatsApp native (Hermes/Meta) keeps today's behavior
                        # (the team replies in the thread the customer already started,
                        # not a new outbound contact) and is intentionally unaffected.
                        consent_gate_active = (
                            bool(getattr(self.runtime.settings, "enable_handoff_consent_gate", False))
                            and audit.channel == "web"
                        )
                        case_status = (
                            SUPPORT_CASE_STATUS_PENDING_CONSENT
                            if consent_gate_active
                            else SUPPORT_CASE_STATUS_OPEN
                        )
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
                                status=case_status,
                            )
                        )
                        if consent_gate_active:
                            # Ticket exists (same atomicity guarantee as always), but
                            # nobody is notified yet: notification is deferred to
                            # POST /web/handoff/consent, after the customer confirms.
                            handoff_status = HANDOFF_PENDING_CONSENT
                        else:
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
                            # Deep link so ficara valido depois que o
                            # SELECT ... deste caso resolver 'aberto' no
                            # bridge (_case_is_open); case_status aqui e
                            # sempre OPEN, nunca pending_consent.
                            support_deep_link = self._maybe_deep_link(support_case_id)
            return ChatPersistenceResult(
                handoff_status=handoff_status,
                persistence_status=PERSISTENCE_PERSISTED,
                turn_id=str(persisted_turn_id),
                request_id_reused=request_id_reused,
                support_deep_link=support_deep_link,
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
        status: str = SUPPORT_CASE_STATUS_OPEN,
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
              reason_codes, context_snapshot_sanitized, idempotency_key, status
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
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
                status,
            ),
        )
        return str(cursor.fetchone()[0]), context_snapshot.get("organized_context")

    def _maybe_deep_link(self, case_id: str) -> str | None:
        """"Continuar no WhatsApp" CTA -- None when the bridge isn't
        configured, so callers simply omit the button/text."""

        settings = self.runtime.settings
        if not getattr(settings, "enable_whatsapp_support_number", False):
            return None
        phone = getattr(settings, "meta_support_phone_number_e164", None)
        token_secret = getattr(settings, "support_wa_token_secret", None)
        if not phone or not token_secret:
            return None
        return build_support_deep_link(
            case_id, support_phone_e164=phone, token_secret=token_secret
        )

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
        customer_name: str | None = None,
        customer_email: str | None = None,
        customer_phone_last4: str | None = None,
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
                customer_name=customer_name,
                customer_email=customer_email,
                customer_phone_last4=customer_phone_last4,
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

    def promote_pending_consent(
        self,
        *,
        request_id: str,
        customer_id: str,
        name: str | None,
        email: str | None,
    ) -> ConsentPromotionResult:
        """Sprint 4b: confirm LGPD consent for a web-chat handoff.

        The support_case already exists (created atomically with the escalated
        turn, see ``record_chat``); this only flips it from ``pending_consent``
        to ``open`` and enqueues the team notification that was deferred until
        now. Idempotent: calling twice for an already-promoted case is a no-op
        that returns the current state instead of double-notifying.
        """
        safe_request_id = safe_feedback_identifier(request_id, field_name="request_id")
        if safe_request_id is None:
            raise ConsentCaseNotFound(request_id)

        clean_name = None
        if name and name.strip():
            clean_name = sanitize_for_persistence(name.strip()[:120])
        clean_email = None
        if email and email.strip():
            candidate = email.strip()[:200]
            if not _EMAIL_PATTERN.fullmatch(candidate):
                raise InvalidConsentContact("email")
            clean_email = candidate

        try:
            with self.runtime.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT sc.id, sc.status, sc.customer_id, sc.opened_at,
                               sc.context_snapshot_sanitized, d.name
                        FROM support_cases sc
                        JOIN domains d ON d.id = sc.domain_id
                        WHERE sc.request_id = %s AND sc.channel = 'web'
                        FOR UPDATE
                        """,
                        (safe_request_id,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ConsentCaseNotFound(safe_request_id)
                    case_id, status, existing_customer_id, opened_at, snapshot, domain_name = row
                    # Ownership: an unclaimed case can be promoted by whoever proves
                    # OTP first; an already-claimed case only accepts its own
                    # customer_id. Mismatch is reported the same as "not found" --
                    # never confirm or deny that a request_id belongs to someone
                    # else's conversation.
                    if existing_customer_id is not None and str(
                        existing_customer_id
                    ) != str(customer_id):
                        raise ConsentCaseNotFound(safe_request_id)

                    snapshot = _load_json_field(snapshot, default={})
                    summary = snapshot.get("summary")
                    references = snapshot.get("references") or []
                    handoff_reasons = snapshot.get("handoff_reasons") or []

                    if status != "pending_consent":
                        return ConsentPromotionResult(
                            support_case_id=str(case_id),
                            status=str(status),
                            opened_at=opened_at,
                            summary=str(summary) if summary else None,
                            domain=str(domain_name),
                            already_promoted=True,
                        )

                    if clean_name or clean_email:
                        cursor.execute(
                            """
                            UPDATE customers
                            SET display_label = COALESCE(display_label, %s),
                                email = COALESCE(email, %s),
                                updated_at = now()
                            WHERE id = %s
                            """,
                            (clean_name, clean_email, customer_id),
                        )

                    # Effective contact after the COALESCE above (an earlier
                    # consent wins over a retyped one). This is the identity the
                    # customer just authorized the team to use, so it enriches
                    # the deferred notification below; the e-mail stays readable
                    # only in `customers` and in this team-facing alert, never in
                    # sanitized payloads or logs.
                    effective_name: str | None = clean_name
                    effective_email: str | None = clean_email
                    phone_last4: str | None = None
                    cursor.execute(
                        """
                        SELECT c.display_label, c.email,
                               (SELECT vi.phone_last4
                                FROM verified_identities vi
                                WHERE vi.customer_id = c.id
                                  AND vi.status = 'verified'
                                ORDER BY vi.verified_at DESC
                                LIMIT 1)
                        FROM customers c
                        WHERE c.id = %s
                        """,
                        (customer_id,),
                    )
                    contact_row = cursor.fetchone()
                    if contact_row is not None:
                        effective_name = contact_row[0] or clean_name
                        effective_email = contact_row[1] or clean_email
                        phone_last4 = contact_row[2]

                    cursor.execute(
                        """
                        UPDATE support_cases
                        SET status = 'open', customer_id = %s, updated_at = now()
                        WHERE id = %s AND status = 'pending_consent'
                        """,
                        (customer_id, case_id),
                    )

                    payload = sanitize_payload(
                        {
                            "request_id": safe_request_id,
                            "domain": domain_name,
                            "support_case_id": str(case_id),
                            "summary": summary,
                        }
                    )
                    cursor.execute(
                        """
                        INSERT INTO operational_outbox (
                          event_type, idempotency_key, request_id, payload_sanitized
                        )
                        VALUES ('handoff.requested', %s, %s, %s::jsonb)
                        ON CONFLICT (idempotency_key) DO NOTHING
                        """,
                        (f"handoff:consent:{case_id}", safe_request_id, json.dumps(payload)),
                    )
                    self._enqueue_support_team_notifications(
                        cursor=cursor,
                        turn_id=str(case_id),
                        support_case_id=str(case_id),
                        request_id=safe_request_id,
                        domain=str(domain_name),
                        handoff_reasons=list(handoff_reasons),
                        summary=str(summary) if summary else "",
                        references=list(references),
                        customer_name=effective_name,
                        customer_email=effective_email,
                        customer_phone_last4=phone_last4,
                    )
        except (ConsentCaseNotFound, InvalidConsentContact):
            raise
        except Exception as exc:
            log_event(
                logger,
                "handoff_consent_promotion_unavailable",
                request_id=safe_request_id,
                error_type=type(exc).__name__,
            )
            raise DatabaseUnavailableError("handoff consent promotion failed") from exc

        return ConsentPromotionResult(
            support_case_id=str(case_id),
            status="open",
            opened_at=opened_at,
            summary=str(summary) if summary else None,
            domain=str(domain_name),
            customer_name=effective_name,
            support_deep_link=self._maybe_deep_link(str(case_id)),
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
