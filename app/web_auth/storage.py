from __future__ import annotations

from threading import Lock
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from app.web_auth.models import OtpChallenge, VerifiedIdentity
from app.db.runtime import DatabaseRuntime


class WebAuthStore(Protocol):
    def save_challenge(self, challenge: OtpChallenge) -> None: ...
    def get_challenge(self, challenge_id: str) -> OtpChallenge | None: ...
    def latest_challenge_for_phone(self, phone_hash: str) -> OtpChallenge | None: ...
    def consume_challenge(
        self,
        challenge_id: str,
        code_digest: str,
        now: datetime,
    ) -> OtpChallenge | None: ...
    def get_identity_for_phone(self, phone_hash: str) -> VerifiedIdentity | None: ...
    def save_identity(self, identity: VerifiedIdentity) -> VerifiedIdentity: ...
    def bind_session(self, session_hash: str, identity: VerifiedIdentity) -> None: ...
    def get_identity_for_session(self, session_hash: str) -> VerifiedIdentity | None: ...
    def clear_session(self, session_hash: str) -> None: ...


class InMemoryWebAuthStore:
    """Lab-only storage seam. Replace with PostgreSQL without changing routes."""

    def __init__(self) -> None:
        self._challenges: dict[str, OtpChallenge] = {}
        self._identities_by_phone: dict[str, VerifiedIdentity] = {}
        self._identity_by_session: dict[str, VerifiedIdentity] = {}
        self._lock = Lock()

    def save_challenge(self, challenge: OtpChallenge) -> None:
        with self._lock:
            self._challenges[challenge.id] = challenge

    def get_challenge(self, challenge_id: str) -> OtpChallenge | None:
        with self._lock:
            return self._challenges.get(challenge_id)

    def latest_challenge_for_phone(self, phone_hash: str) -> OtpChallenge | None:
        with self._lock:
            matches = [
                challenge
                for challenge in self._challenges.values()
                if challenge.phone_hash == phone_hash
            ]
        return max(matches, key=lambda challenge: challenge.created_at, default=None)

    def get_identity_for_phone(self, phone_hash: str) -> VerifiedIdentity | None:
        with self._lock:
            return self._identities_by_phone.get(phone_hash)

    def consume_challenge(
        self,
        challenge_id: str,
        code_digest: str,
        now: datetime,
    ) -> OtpChallenge | None:
        with self._lock:
            challenge = self._challenges.get(challenge_id)
            if (
                challenge is None
                or challenge.status != "pending"
                or challenge.expires_at <= now
                or challenge.attempts_remaining <= 0
            ):
                return None
            if challenge.code_digest != code_digest:
                challenge.attempts_remaining -= 1
                if challenge.attempts_remaining <= 0:
                    challenge.status = "exhausted"
                return None
            challenge.status = "consumed"
            return challenge

    def save_identity(self, identity: VerifiedIdentity) -> VerifiedIdentity:
        with self._lock:
            self._identities_by_phone[identity.phone_hash] = identity
        return identity

    def bind_session(self, session_hash: str, identity: VerifiedIdentity) -> None:
        with self._lock:
            self._identity_by_session[session_hash] = identity

    def get_identity_for_session(self, session_hash: str) -> VerifiedIdentity | None:
        with self._lock:
            return self._identity_by_session.get(session_hash)

    def clear_session(self, session_hash: str) -> None:
        with self._lock:
            self._identity_by_session.pop(session_hash, None)


class PostgresWebAuthStore:
    def __init__(self, runtime: DatabaseRuntime) -> None:
        self.runtime = runtime

    def save_challenge(self, challenge: OtpChallenge) -> None:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO otp_challenges (
                      id, identity_candidate_hash, phone_last4, code_digest,
                      expires_at, attempts_remaining, status, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      attempts_remaining = EXCLUDED.attempts_remaining,
                      status = EXCLUDED.status,
                      consumed_at = CASE WHEN EXCLUDED.status = 'consumed' THEN now() ELSE otp_challenges.consumed_at END
                    """,
                    (
                        challenge.id,
                        challenge.phone_hash,
                        challenge.phone_last4,
                        challenge.code_digest,
                        challenge.expires_at,
                        challenge.attempts_remaining,
                        challenge.status,
                        challenge.created_at,
                    ),
                )

    def get_challenge(self, challenge_id: str) -> OtpChallenge | None:
        return self._find_challenge("id = %s", (challenge_id,))

    def latest_challenge_for_phone(self, phone_hash: str) -> OtpChallenge | None:
        return self._find_challenge(
            "identity_candidate_hash = %s ORDER BY created_at DESC",
            (phone_hash,),
        )

    def consume_challenge(
        self,
        challenge_id: str,
        code_digest: str,
        now: datetime,
    ) -> OtpChallenge | None:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, identity_candidate_hash, phone_last4, code_digest,
                           created_at, expires_at, attempts_remaining, status
                    FROM otp_challenges
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (challenge_id,),
                )
                row = cursor.fetchone()
                challenge = self._to_challenge(row)
                if (
                    challenge is None
                    or challenge.status != "pending"
                    or challenge.expires_at <= now
                    or challenge.attempts_remaining <= 0
                ):
                    return None
                if challenge.code_digest != code_digest:
                    attempts = challenge.attempts_remaining - 1
                    status = "exhausted" if attempts <= 0 else "pending"
                    cursor.execute(
                        "UPDATE otp_challenges SET attempts_remaining = %s, status = %s WHERE id = %s",
                        (attempts, status, challenge.id),
                    )
                    return None
                cursor.execute(
                    "UPDATE otp_challenges SET status = 'consumed', consumed_at = now() WHERE id = %s",
                    (challenge.id,),
                )
                challenge.status = "consumed"
                return challenge

    def get_identity_for_phone(self, phone_hash: str) -> VerifiedIdentity | None:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, phone_hash, phone_last4, verified_at, status
                    FROM verified_identities
                    WHERE channel = 'whatsapp' AND phone_hash = %s
                    """,
                    (phone_hash,),
                )
                return self._to_identity(cursor.fetchone())

    def save_identity(self, identity: VerifiedIdentity) -> VerifiedIdentity:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO verified_identities (
                      id, channel, phone_hash, phone_last4, verified_at, status
                    )
                    VALUES (%s, 'whatsapp', %s, %s, %s, %s)
                    ON CONFLICT (channel, phone_hash) DO UPDATE
                    SET verified_at = EXCLUDED.verified_at, status = EXCLUDED.status,
                        updated_at = now()
                    RETURNING id, phone_hash, phone_last4, verified_at, status
                    """,
                    (
                        identity.id or str(uuid4()),
                        identity.phone_hash,
                        identity.phone_last4,
                        identity.verified_at,
                        identity.status,
                    ),
                )
                saved = self._to_identity(cursor.fetchone())
                if saved is None:
                    raise RuntimeError("identity persistence returned no row")
                return saved

    def bind_session(self, session_hash: str, identity: VerifiedIdentity) -> None:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO web_sessions (anonymous_session_hash, verified_identity_id)
                    VALUES (%s, %s)
                    ON CONFLICT (anonymous_session_hash) DO UPDATE
                    SET verified_identity_id = EXCLUDED.verified_identity_id, last_seen_at = now()
                    """,
                    (session_hash, identity.id),
                )

    def get_identity_for_session(self, session_hash: str) -> VerifiedIdentity | None:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT i.id, i.phone_hash, i.phone_last4, i.verified_at, i.status
                    FROM web_sessions s
                    JOIN verified_identities i ON i.id = s.verified_identity_id
                    WHERE s.anonymous_session_hash = %s AND i.status = 'verified'
                    """,
                    (session_hash,),
                )
                return self._to_identity(cursor.fetchone())

    def clear_session(self, session_hash: str) -> None:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE web_sessions SET verified_identity_id = NULL, last_seen_at = now() WHERE anonymous_session_hash = %s",
                    (session_hash,),
                )

    def _find_challenge(self, predicate: str, params: tuple) -> OtpChallenge | None:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT id, identity_candidate_hash, phone_last4, code_digest,
                           created_at, expires_at, attempts_remaining, status
                    FROM otp_challenges WHERE {predicate} LIMIT 1
                    """,
                    params,
                )
                return self._to_challenge(cursor.fetchone())

    @staticmethod
    def _to_challenge(row) -> OtpChallenge | None:
        if row is None:
            return None
        return OtpChallenge(
            id=str(row[0]),
            phone_hash=row[1],
            phone_last4=row[2],
            code_digest=row[3],
            created_at=row[4],
            expires_at=row[5],
            attempts_remaining=row[6],
            status=row[7],
        )

    @staticmethod
    def _to_identity(row) -> VerifiedIdentity | None:
        if row is None:
            return None
        return VerifiedIdentity(
            id=str(row[0]),
            phone_hash=row[1],
            phone_last4=row[2],
            verified_at=row[3],
            status=row[4],
        )
