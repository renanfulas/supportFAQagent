from __future__ import annotations

from threading import Lock

from app.web_auth.models import OtpChallenge, VerifiedIdentity


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

    def save_identity(self, identity: VerifiedIdentity) -> None:
        with self._lock:
            self._identities_by_phone[identity.phone_hash] = identity

    def bind_session(self, session_hash: str, identity: VerifiedIdentity) -> None:
        with self._lock:
            self._identity_by_session[session_hash] = identity

    def get_identity_for_session(self, session_hash: str) -> VerifiedIdentity | None:
        with self._lock:
            return self._identity_by_session.get(session_hash)

    def clear_session(self, session_hash: str) -> None:
        with self._lock:
            self._identity_by_session.pop(session_hash, None)
