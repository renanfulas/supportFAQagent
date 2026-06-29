"""Nightly conversation summarization (layered-persistence plan, Fase 3).

Pure, testable helpers plus a DB batch that reads *closed/inactive* conversations,
sanitizes every turn **before** it can reach the model, asks a cheap model for a
structured record (problem/solution/status) and upserts it idempotently into the
``conversation_summaries`` warehouse. No raw PII, no raw ``session_id``.

The model provider is injected (``generate_answer(prompt) -> str``) so the script
uses the real ``LLMWrapper`` and tests use a fake.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from app.core.persistence_sanitize import REDACTION_VERSION, sanitize_for_persistence


VALID_STATUSES = {"resolvido", "em_aberto", "escalado"}


class SummaryProvider(Protocol):
    def generate_answer(self, prompt: str) -> str: ...


@dataclass(frozen=True)
class ConversationSummaryRecord:
    domain: str
    customer_ref: str
    problem: str
    solution: str
    status: str
    source_turn_count: int
    redaction_version: str
    model: str
    conversation_key: str


def build_transcript(turns: Iterable[tuple[str, str]]) -> str:
    """``turns`` = ordered ``(role, content)``. Each turn is redacted before it can
    reach the summarization model (PAN/PII never leaves the boundary unredacted)."""
    lines: list[str] = []
    for role, content in turns:
        safe = sanitize_for_persistence(content) or ""
        speaker = "Cliente" if role == "user" else "Agente"
        lines.append(f"{speaker}: {safe}")
    return "\n".join(lines)


def build_summary_prompt(transcript: str) -> str:
    return (
        "Voce resume conversas de atendimento. Leia a conversa e responda APENAS "
        "com um objeto JSON, sem texto fora do JSON.\n"
        "Campos:\n"
        '  - "problem": o problema/objetivo do cliente, em uma frase factual.\n'
        '  - "solution": a solucao dada ou tentada, em uma frase factual.\n'
        '  - "status": exatamente um de "resolvido", "em_aberto", "escalado".\n'
        "Nao invente dados que nao estao na conversa.\n\n"
        f"CONVERSA:\n{transcript}\n\n"
        'JSON: {"problem": "...", "solution": "...", "status": "..."}'
    )


def parse_summary_json(raw: str) -> dict[str, str]:
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        raise ValueError("summary response had no JSON object")
    data = json.loads(match.group(0))
    problem = str(data.get("problem", "")).strip()
    solution = str(data.get("solution", "")).strip()
    status = str(data.get("status", "")).strip().lower()
    if status not in VALID_STATUSES:
        status = "em_aberto"
    if not problem:
        raise ValueError("summary is missing 'problem'")
    return {"problem": problem, "solution": solution, "status": status}


def summarize_turns(
    *, turns: list[tuple[str, str]], provider: SummaryProvider
) -> dict[str, str]:
    raw = provider.generate_answer(build_summary_prompt(build_transcript(turns)))
    return parse_summary_json(raw)


def derive_customer_ref(customer_id: Any, session_hash: str | None) -> str:
    if customer_id:
        return str(customer_id)
    if session_hash:
        return session_hash
    return "unknown"


def run_summary_batch(
    connection: Any,
    provider: SummaryProvider,
    *,
    model: str,
    inactivity_hours: int = 24,
    min_turns: int = 2,
    limit: int = 100,
    force: bool = False,
) -> dict[str, int]:
    """Summarize eligible (inactive, non-trivial, not-yet-summarized) conversations.

    Idempotent: UNIQUE (domain, conversation_key) + ON CONFLICT upsert. ``force``
    re-summarizes already-summarized conversations (costs model calls)."""
    stats = {"eligible": 0, "summarized": 0, "errors": 0}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.id, d.name, c.customer_id, c.session_hash
            FROM conversations c
            JOIN domains d ON d.id = c.domain_id
            WHERE c.last_message_at IS NOT NULL
              AND c.last_message_at < now() - make_interval(hours => %s)
              AND (
                SELECT count(*) FROM messages m WHERE m.conversation_id = c.id
              ) >= %s
              AND (
                %s OR NOT EXISTS (
                  SELECT 1 FROM conversation_summaries s
                  WHERE s.domain = d.name AND s.conversation_key = c.id::text
                )
              )
            ORDER BY c.last_message_at DESC
            LIMIT %s
            """,
            (inactivity_hours, min_turns, force, limit),
        )
        candidates = cursor.fetchall()

    stats["eligible"] = len(candidates)
    for conv_id, domain_name, customer_id, session_hash in candidates:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT role, content FROM messages
                    WHERE conversation_id = %s
                    ORDER BY created_at, message_sequence
                    """,
                    (conv_id,),
                )
                turns = [(str(role), str(content)) for role, content in cursor.fetchall()]
            summary = summarize_turns(turns=turns, provider=provider)
            record = ConversationSummaryRecord(
                domain=str(domain_name),
                customer_ref=derive_customer_ref(customer_id, session_hash),
                problem=summary["problem"],
                solution=summary["solution"],
                status=summary["status"],
                source_turn_count=len(turns),
                redaction_version=REDACTION_VERSION,
                model=model,
                conversation_key=str(conv_id),
            )
            _upsert_summary(connection, record)
            stats["summarized"] += 1
        except Exception:  # noqa: BLE001 - one bad conversation must not stop the batch
            stats["errors"] += 1
    return stats


def _upsert_summary(connection: Any, record: ConversationSummaryRecord) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO conversation_summaries (
              domain, customer_ref, problem, solution, status,
              source_turn_count, redaction_version, model, conversation_key
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (domain, conversation_key) DO UPDATE SET
              customer_ref = EXCLUDED.customer_ref,
              problem = EXCLUDED.problem,
              solution = EXCLUDED.solution,
              status = EXCLUDED.status,
              source_turn_count = EXCLUDED.source_turn_count,
              redaction_version = EXCLUDED.redaction_version,
              model = EXCLUDED.model,
              summarized_at = now()
            """,
            (
                record.domain,
                record.customer_ref,
                record.problem,
                record.solution,
                record.status,
                record.source_turn_count,
                record.redaction_version,
                record.model,
                record.conversation_key,
            ),
        )
    connection.commit()
