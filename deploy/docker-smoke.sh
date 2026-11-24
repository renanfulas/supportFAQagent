#!/usr/bin/env bash
# Smoke do pacote de producao (docker-compose.prod.yml) num projeto descartavel.
#
#   bash deploy/docker-smoke.sh                      # builda a imagem local
#   SUPPORTFAQ_IMAGE=supportfaqagent:ci bash deploy/docker-smoke.sh   # usa imagem pronta
#
# Sobe app + postgres com segredos aleatorios de uso unico, prova o start seguro
# (banco novo migra, restart nao migra de novo), os endpoints, o usuario nao-root
# e que nenhum segredo nem session_id cru aparece no log. No fim apaga o projeto
# inteiro, inclusive os volumes DELE (nunca os de uma instalacao real: o nome do
# projeto precisa comecar com "sfaq-smoke").
#
# Roda no CI (.github/workflows/docker-image.yml) e na maquina do operador.
# Runbook: docs/runbooks/docker-install.md

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export COMPOSE_PROJECT_NAME="${SMOKE_PROJECT:-sfaq-smoke}"
case "$COMPOSE_PROJECT_NAME" in
  sfaq-smoke*) ;;
  *) echo "smoke: SMOKE_PROJECT must start with sfaq-smoke" >&2; exit 2 ;;
esac
APP_PORT="${SMOKE_APP_PORT:-18080}"
BASE="http://127.0.0.1:${APP_PORT}"
COMPOSE=(docker compose -f docker-compose.prod.yml)
SESSION_ID="smoke-session-$RANDOM$RANDOM"

if [ -e .env ]; then
  # O compose le .env da raiz: o smoke nunca sobrescreve uma configuracao real.
  echo "smoke: refusing to run, .env already exists in $ROOT" >&2
  exit 2
fi

rand() {
  python3 -c 'import secrets; print(secrets.token_hex(24))' 2>/dev/null \
    || python -c 'import secrets; print(secrets.token_hex(24))'
}

cleanup() {
  local status=$?
  if [ "$status" -ne 0 ]; then
    echo "smoke: FAILED, last app logs:" >&2
    "${COMPOSE[@]}" ps >&2 || true
    "${COMPOSE[@]}" logs --tail 80 app >&2 || true
  fi
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  rm -f .env
  exit "$status"
}
trap cleanup EXIT

fail() {
  echo "smoke: FAIL $*" >&2
  exit 1
}

expect_status() {
  local expected=$1 path=$2
  shift 2
  local got
  got=$(curl -s -o /dev/null -w '%{http_code}' "$@" "${BASE}${path}")
  [ "$got" = "$expected" ] || fail "$path returned $got, expected $expected"
  echo "smoke: ok $path -> $got"
}

# --- configuracao de uso unico ----------------------------------------------------
API_KEY=$(rand)
DB_PASSWORD=$(rand)
HASH_SECRET=$(rand)
sed \
  -e "s|^API_SECRET_KEY=.*|API_SECRET_KEY=${API_KEY}|" \
  -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${DB_PASSWORD}|" \
  -e "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://supportfaq:${DB_PASSWORD}@postgres:5432/supportfaq|" \
  -e "s|^PERSISTENCE_HASH_SECRET=.*|PERSISTENCE_HASH_SECRET=${HASH_SECRET}|" \
  -e "s|^APP_PORT=.*|APP_PORT=${APP_PORT}|" \
  deploy/production.env.example > .env
if grep -v '^#' .env | grep -q '<set-private-value>'; then
  fail "a placeholder was left in the smoke .env"
fi

# --- subir ------------------------------------------------------------------------
UP_ARGS=(up -d --wait --wait-timeout 240)
if [ -n "${SUPPORTFAQ_IMAGE:-}" ]; then
  UP_ARGS+=(--no-build)
else
  UP_ARGS+=(--build)
fi
"${COMPOSE[@]}" "${UP_ARGS[@]}"

logs() { "${COMPOSE[@]}" logs --no-color app 2>&1; }
count() { logs | grep -c -- "$1" || true; }

[ "$(count 'safe_start: new database detected')" = 1 ] || fail "bootstrap did not run on the new database"
[ "$(count 'safe_start: readiness passed')" = 1 ] || fail "readiness gate did not pass"

# --- endpoints --------------------------------------------------------------------
expect_status 200 /health
expect_status 403 /domains
expect_status 200 /domains -H "X-API-Key: ${API_KEY}"
expect_status 200 /health/ready -H "X-API-Key: ${API_KEY}"
expect_status 200 /chat -H "X-API-Key: ${API_KEY}" -H 'Content-Type: application/json' \
  -d "{\"message\":\"como reiniciar minha vps?\",\"session_id\":\"${SESSION_ID}\"}"
expect_status 404 /chat-ui

# --- container endurecido ---------------------------------------------------------
[ "$("${COMPOSE[@]}" exec -T app id -u | tr -d '\r')" = 10001 ] || fail "app is not running as uid 10001"
if "${COMPOSE[@]}" exec -T app sh -c 'touch /app/smoke-write' >/dev/null 2>&1; then
  fail "/app is writable"
fi
echo "smoke: ok non-root, read-only code"

# --- restart nao migra de novo ----------------------------------------------------
"${COMPOSE[@]}" restart app >/dev/null
"${COMPOSE[@]}" up -d --wait --wait-timeout 240 --no-build app >/dev/null
[ "$(count 'safe_start: new database detected')" = 1 ] || fail "restart re-ran the bootstrap"
[ "$(count 'safe_start: readiness passed')" = 2 ] || fail "restart did not pass readiness"
echo "smoke: ok restart skips bootstrap"

# --- privacidade do log -----------------------------------------------------------
for value in "$API_KEY" "$DB_PASSWORD" "$HASH_SECRET" "$SESSION_ID"; do
  if logs | grep -q -- "$value"; then
    fail "a secret or raw session_id leaked into the app log"
  fi
done
echo "smoke: ok no secret or raw session_id in logs"

echo "smoke: PASSED"
