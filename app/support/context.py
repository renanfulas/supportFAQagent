"""Pure assembler that turns a durable support case plus its persisted
conversation into an organized, sanitized context structure.

This is the reusable seam: the read surface serves it now, and the push
payload (operational outbox) can reuse the same builder later so both
deliveries describe a handoff the same way. The builder never touches the
database or performs sanitization — it only organizes values that were
already sanitized on write.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence


# Bounds for the push-side snapshot copy. The read surface serves the full
# transcript on demand; the snapshot embedded in the outbox payload stays small
# so it fits well under the verified-webhook body budget.
SNAPSHOT_MAX_TURNS = 12
SNAPSHOT_TURN_CONTENT_LIMIT = 1000


@dataclass(frozen=True)
class TranscriptTurn:
    sequence: int
    role: str
    content: str
    confidence: float | None
    escalated: bool
    handoff_reasons: list[str]
    references: list[str]
    error_code: str | None
    created_at: datetime | None


@dataclass(frozen=True)
class SupportCaseCustomer:
    """Contact the customer authorized for direct follow-up (LGPD consent).

    Sourced from the ``customers`` row joined on read (single source of truth,
    so a replayed turn overwriting the case snapshot can never lose it). The
    e-mail is stored readable on purpose — the team uses it for real contact —
    and is exposed only on this authenticated internal surface.
    """

    display_label: str | None
    email: str | None
    phone_last4: str | None


@dataclass(frozen=True)
class SupportCaseContext:
    case_id: str
    domain: str
    status: str
    priority: str
    channel: str
    request_id: str
    reason_codes: list[str]
    summary: str | None
    references: list[str]
    transcript: list[TranscriptTurn]
    turn_count: int
    opened_at: datetime | None
    updated_at: datetime | None
    customer: SupportCaseCustomer | None = None


def build_case_context(
    case: Mapping[str, Any],
    transcript_rows: Sequence[Mapping[str, Any]],
) -> SupportCaseContext:
    """Assemble an organized context for a single support case.

    ``case`` carries the support_cases row joined with its domain name and
    sanitized context snapshot. ``transcript_rows`` are the persisted
    user/assistant messages for the linked conversation, ordered oldest first.
    """

    snapshot = case.get("context_snapshot") or {}
    transcript = [_to_turn(row) for row in transcript_rows]
    references = _aggregate_references(snapshot, transcript)

    customer = None
    customer_fields = (
        _optional_str(case.get("customer_display_label")),
        _optional_str(case.get("customer_email")),
        _optional_str(case.get("customer_phone_last4")),
    )
    if any(customer_fields):
        customer = SupportCaseCustomer(
            display_label=customer_fields[0],
            email=customer_fields[1],
            phone_last4=customer_fields[2],
        )

    return SupportCaseContext(
        case_id=str(case["id"]),
        domain=str(case["domain"]),
        status=str(case["status"]),
        priority=str(case["priority"]),
        channel=str(case["channel"]),
        request_id=str(case["request_id"]),
        reason_codes=_as_str_list(case.get("reason_codes")),
        summary=_optional_str(snapshot.get("summary")),
        references=references,
        transcript=transcript,
        turn_count=len(transcript),
        opened_at=case.get("opened_at"),
        updated_at=case.get("updated_at"),
        customer=customer,
    )


def build_snapshot_context(
    recent_turn_rows: Sequence[Mapping[str, Any]],
    *,
    total_turn_count: int,
    content_limit: int = SNAPSHOT_TURN_CONTENT_LIMIT,
) -> dict[str, Any]:
    """Build the bounded organized-context block stored on a support case.

    ``recent_turn_rows`` are the already-bounded most-recent turns (oldest
    first). ``total_turn_count`` is the true conversation length so a consumer
    knows whether earlier turns were elided. Shares ``_to_turn`` and
    ``_aggregate_references`` with :func:`build_case_context` so the push copy
    describes the handoff the same way the read surface does.
    """

    turns = [_to_turn(row) for row in recent_turn_rows]
    return {
        "turn_count": int(total_turn_count),
        "included_turn_count": len(turns),
        "references": _aggregate_references({}, turns),
        "recent_turns": [
            {
                "sequence": turn.sequence,
                "role": turn.role,
                "content": turn.content[:content_limit],
            }
            for turn in turns
        ],
    }


def _to_turn(row: Mapping[str, Any]) -> TranscriptTurn:
    confidence = row.get("confidence")
    return TranscriptTurn(
        sequence=int(row["sequence"]),
        role=str(row["role"]),
        content=str(row["content"]),
        confidence=float(confidence) if confidence is not None else None,
        escalated=bool(row.get("escalated")),
        handoff_reasons=_as_str_list(row.get("handoff_reasons")),
        references=_as_str_list(row.get("references")),
        error_code=_optional_str(row.get("error_code")),
        created_at=row.get("created_at"),
    )


def _aggregate_references(
    snapshot: Mapping[str, Any],
    transcript: Sequence[TranscriptTurn],
) -> list[str]:
    """Union of snapshot references and per-turn references, order-preserving."""

    seen: dict[str, None] = {}
    for reference in _as_str_list(snapshot.get("references")):
        seen.setdefault(reference, None)
    for turn in transcript:
        for reference in turn.references:
            seen.setdefault(reference, None)
    return list(seen.keys())


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
