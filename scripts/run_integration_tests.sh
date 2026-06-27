#!/usr/bin/env bash
#
# Run the gated PostgreSQL integration suite locally against a disposable
# pgvector database started by docker-compose.test.yml.
#
# The integration tests skip unless PHASE0_TEST_DATABASE_URL is set. This script
# starts a throwaway Postgres, exports the required env vars, applies migrations,
# runs the suite, and tears the database down again. It does NOT change the
# skip gating: without this script (or the env vars) the suite still skips.
#
# Usage:
#   ./scripts/run_integration_tests.sh            # full lifecycle, then teardown
#   KEEP_DB=1 ./scripts/run_integration_tests.sh  # leave the DB running on exit
#
# Requires: docker + docker compose, and `pip install -e ".[dev]"`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT}/docker-compose.test.yml"
SERVICE="postgres_test"

# Lab-only, disposable connection. Must match docker-compose.test.yml and keep a
# database name that matches (test|phase0|disposable) for the conftest guard.
export PHASE0_TEST_DATABASE_URL="postgresql://postgres:throwaway_test_password@127.0.0.1:55432/supportfaq_phase0"
export PHASE0_TEST_DATABASE_DISPOSABLE="true"
export DATABASE_URL="${PHASE0_TEST_DATABASE_URL}"
export PERSISTENCE_HASH_SECRET="local-phase0-test-secret"
export PERSISTENCE_HASH_VERSION="hmac-sha256-v1"

cleanup() {
  if [ "${KEEP_DB:-0}" = "1" ]; then
    echo "KEEP_DB=1 set; leaving disposable Postgres running."
    return
  fi
  echo "Tearing down disposable Postgres..."
  docker compose -f "${COMPOSE_FILE}" down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Starting disposable Postgres (pgvector)..."
docker compose -f "${COMPOSE_FILE}" up -d

echo "Waiting for Postgres to become healthy..."
for _ in $(seq 1 40); do
  status="$(docker inspect -f '{{.State.Health.Status}}' supportfaq_postgres_test 2>/dev/null || echo unknown)"
  if [ "${status}" = "healthy" ]; then
    break
  fi
  sleep 2
done
if [ "${status:-unknown}" != "healthy" ]; then
  echo "Postgres did not become healthy in time." >&2
  exit 1
fi

echo "Applying migrations..."
python -m scripts.migrate apply

echo "Running integration suite..."
python -m pytest tests/integration -q "$@"
