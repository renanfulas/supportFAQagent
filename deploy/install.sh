#!/usr/bin/env bash
# Instalacao guiada do supportFAQagent numa empresa (single-tenant).
#
#   bash deploy/install.sh [--client-pack DIR] [--admin-phone +55... --admin-name "Nome"]
#                          [--skip-evals] [--report install-report.md]
#
# 1. Gera o .env com valores aleatorios e privados (chmod 600), se ainda nao
#    existir. Um .env existente nunca e sobrescrito.
# 2. Sobe a stack; o start seguro migra o banco novo e espera o readiness.
# 3. Roda scripts.post_install no container: registra os dominios, cadastra o
#    primeiro operador (opcional) e roda os evals de confinamento.
# 4. Smoke HTTP na API e grava o relatorio de instalacao (sem segredos).
#
# Nunca apaga volume nem dado. Pode rodar de novo: reaproveita o .env e o banco.
# Saida: 0 ok, 1 falhou, 2 argumento/configuracao invalida, 3 instalada com eval falhando.
# Runbook: docs/runbooks/docker-install.md

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f docker-compose.prod.yml)
REPORT="install-report.md"
CLIENT_PACK=""
POST_ARGS=()

usage() {
  sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
}

log() { echo "init: $*" >&2; }
die() { echo "init: ERROR $1" >&2; exit "${2:-1}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --client-pack) CLIENT_PACK="${2:?--client-pack needs a folder}"; shift 2 ;;
    --admin-phone) POST_ARGS+=(--admin-phone "${2:?--admin-phone needs a phone}"); shift 2 ;;
    --admin-name) POST_ARGS+=(--admin-name "${2:?--admin-name needs a name}"); shift 2 ;;
    --skip-evals) POST_ARGS+=(--skip-evals); shift ;;
    --report) REPORT="${2:?--report needs a file}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1 (see --help)" 2 ;;
  esac
done

rand() {
  openssl rand -hex 24 2>/dev/null \
    || python3 -c 'import secrets; print(secrets.token_hex(24))' 2>/dev/null \
    || od -An -tx1 -N24 /dev/urandom | tr -d ' \n'
}

env_value() {
  # Valor de uma variavel do .env, sem imprimir nada no log.
  grep -E "^$1=" .env | tail -n 1 | cut -d= -f2-
}

# --- 1. configuracao --------------------------------------------------------------
if [ -e .env ]; then
  [ -z "$CLIENT_PACK" ] || die ".env already exists; set CLIENT_PACK_DIR in it instead of --client-pack" 2
  log "reusing the existing .env (never overwritten)"
else
  DB_PASSWORD=$(rand)
  (
    umask 077
    sed \
      -e "s|^API_SECRET_KEY=.*|API_SECRET_KEY=$(rand)|" \
      -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${DB_PASSWORD}|" \
      -e "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://supportfaq:${DB_PASSWORD}@postgres:5432/supportfaq|" \
      -e "s|^PERSISTENCE_HASH_SECRET=.*|PERSISTENCE_HASH_SECRET=$(rand)|" \
      -e "s|^IDENTITY_HASH_SECRET=.*|IDENTITY_HASH_SECRET=$(rand)|" \
      ${CLIENT_PACK:+-e "s|^CLIENT_PACK_DIR=.*|CLIENT_PACK_DIR=${CLIENT_PACK}|"} \
      deploy/production.env.example > .env
  )
  chmod 600 .env
  unset DB_PASSWORD
  log "generated .env with random private values (chmod 600); keep it out of Git and back it up"
fi

if grep -v '^#' .env | grep -q '<set-private-value>'; then
  die "fill every <set-private-value> in .env before installing" 2
fi
PACK_DIR="$(env_value CLIENT_PACK_DIR)"
PACK_DIR="${PACK_DIR:-./domains}"
[ -d "$PACK_DIR" ] || die "client pack folder not found: $PACK_DIR" 2

# --- 2. subir ---------------------------------------------------------------------
IMAGE="${SUPPORTFAQ_IMAGE:-$(env_value SUPPORTFAQ_IMAGE || true)}"
if [ -n "$IMAGE" ]; then
  log "using published image ${IMAGE}"
  "${COMPOSE[@]}" pull app
  UP_BUILD=(--no-build)
else
  log "building the image from this checkout"
  UP_BUILD=(--build)
fi
if ! "${COMPOSE[@]}" up -d --wait --wait-timeout 300 "${UP_BUILD[@]}"; then
  "${COMPOSE[@]}" logs --tail 40 app >&2 || true
  die "the stack did not become healthy; the safe_start lines above say why"
fi
log "stack is up and passed readiness"

# --- 3. pos-instalacao no container -----------------------------------------------
REPORT_TMP="${REPORT}.tmp"
set +e
"${COMPOSE[@]}" run --rm -T app python -m scripts.post_install ${POST_ARGS[@]+"${POST_ARGS[@]}"} > "$REPORT_TMP"
POST_STATUS=$?
set -e
if [ "$POST_STATUS" -eq 2 ]; then
  rm -f "$REPORT_TMP"
  die "post-install rejected the arguments or the configuration" 2
fi

# --- 4. smoke HTTP ----------------------------------------------------------------
API_KEY="$(env_value API_SECRET_KEY)"
BASE="http://127.0.0.1:$(env_value APP_PORT || true)"
[ "$BASE" != "http://127.0.0.1:" ] || BASE="http://127.0.0.1:8000"
SMOKE_STATUS=0
check() {
  local expected=$1 label=$2 path=$3
  shift 3
  local got
  got=$(curl -s -o /dev/null -w '%{http_code}' "$@" "${BASE}${path}" || true)
  if [ "$got" = "$expected" ]; then
    echo "| ${label} | ✅ ${got} |"
  else
    echo "| ${label} | ❌ ${got} (esperado ${expected}) |"
    SMOKE_STATUS=1
  fi
}
{
  echo
  echo "## Smoke HTTP"
  echo
  echo "| Checagem | Resultado |"
  echo "| --- | --- |"
  check 200 "GET /health" /health
  check 200 "GET /health/ready" /health/ready -H "X-API-Key: ${API_KEY}"
  check 200 "GET /domains" /domains -H "X-API-Key: ${API_KEY}"
  check 200 "POST /chat" /chat -H "X-API-Key: ${API_KEY}" -H 'Content-Type: application/json' \
    -d '{"message":"ola, preciso de ajuda"}'
  echo
} > "${REPORT_TMP}.smoke"
unset API_KEY
# shellcheck disable=SC2015
grep -q '❌' "${REPORT_TMP}.smoke" && SMOKE_STATUS=1 || true

cat "$REPORT_TMP" "${REPORT_TMP}.smoke" > "$REPORT"
rm -f "$REPORT_TMP" "${REPORT_TMP}.smoke"

STATUS=$POST_STATUS
[ "$SMOKE_STATUS" -eq 0 ] || STATUS=1
case "$STATUS" in
  0) log "installation complete; report: $REPORT" ;;
  3) log "installed, but some evals failed; report: $REPORT" ;;
  *) log "installation incomplete; report: $REPORT" ;;
esac
exit "$STATUS"
