"""Deterministic defaults that keep the test suite isolated from private .env."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("API_SECRET_KEY", "local-dev-api-key")
os.environ.setdefault("RETRIEVAL_BACKEND", "lexical")
os.environ.setdefault("PERSISTENCE_BACKEND", "disabled")
os.environ.setdefault("WEB_AUTH_STORAGE_BACKEND", "memory")
os.environ.setdefault("ENABLE_OUTBOX_INGRESS", "false")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "")


def create_test_client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app())
