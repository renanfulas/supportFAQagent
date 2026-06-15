"""Safety guard for destructive PostgreSQL integration tests."""

from __future__ import annotations

import os
import re

import pytest


def pytest_sessionstart(session: pytest.Session) -> None:
    _ = session
    database_url = os.getenv("PHASE0_TEST_DATABASE_URL")
    if not database_url:
        return
    if os.getenv("PHASE0_TEST_DATABASE_DISPOSABLE", "").lower() != "true":
        pytest.exit(
            "refusing PostgreSQL integration tests without "
            "PHASE0_TEST_DATABASE_DISPOSABLE=true",
        )

    from psycopg.conninfo import conninfo_to_dict

    database_name = conninfo_to_dict(database_url).get("dbname", "")
    if not re.search(r"(test|phase0|disposable)", database_name, re.IGNORECASE):
        pytest.exit(
            "refusing PostgreSQL integration tests against a database whose "
            "name is not explicitly disposable",
        )
