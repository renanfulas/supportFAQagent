from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class OtpChallenge:
    id: str
    phone_hash: str
    phone_last4: str
    code_digest: str
    created_at: datetime
    expires_at: datetime
    attempts_remaining: int
    status: str = "pending"
    # Fase 3 (opcional, opt-in): hash de dominio nativo recalculado em
    # start() -- unico momento em que o telefone bruto existe em memoria --
    # e carregado ate confirm() consumir o desafio. None quando a Fase 3 nao
    # esta configurada (PERSISTENCE_HASH_SECRET ausente) ou o telefone e
    # invalido para o formato esperado.
    native_session_hash_hermes: str | None = None
    native_session_hash_meta: str | None = None


@dataclass
class VerifiedIdentity:
    id: str
    phone_hash: str
    phone_last4: str
    verified_at: datetime
    status: str = "verified"
    customer_id: str | None = None


@dataclass(frozen=True)
class OtpDeliveryRequest:
    challenge_id: str
    phone: str
    code: str
    expires_in_seconds: int
