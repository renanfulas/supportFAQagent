#!/usr/bin/env bash
# Instalacao guiada do supportFAQagent numa empresa (single-tenant).
#
#   bash deploy/install.sh [--profile minimo|padrao|completo] [--client-pack DIR]
#                          [--new-domain NOME --display-name "Nome" [--owner "Time"]]
#                          [--pgvector] [--admin-phone +55... --admin-name "Nome"]
#                          [--skip-evals] [--report install-report.md]
#
# 1. Gera o .env a partir do perfil (padrao: minimo) com valores aleatorios e
#    privados (chmod 600), se ainda nao existir. Um .env existente nunca e
#    regerado; o CONFIG_PROFILE dele decide o perfil.
# 2. --new-domain cria o primeiro dominio no pacote do cliente (scaffold validado
#    com as suites de confinamento); num .env novo ele vira o DEFAULT_DOMAIN.
#    Dominio que ja existe fica intocado.
# 3. Para se faltar valor de fornecedor (<set-provider-value>) e roda o config
#    validate na imagem: nada sobe com configuracao invalida.
# 4. Sobe a stack; o start seguro migra o banco novo e espera o readiness.
# 5. --pgvector sincroniza o pacote no pgvector (rodar de novo nao duplica nem
#    paga embedding do que nao mudou) e so troca RETRIEVAL_BACKEND para pgvector
#    se a ingestao passar e o readiness aceitar; senao volta para lexical.
# 6. Roda scripts.post_install no container: registra os dominios, cadastra o
#    primeiro operador (opcional) e roda os evals de confinamento.
# 7. Smoke HTTP na API e grava o relatorio de instalacao (sem segredos).
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
PROFILE=""
NEW_DOMAIN=""
DISPLAY_NAME=""
OWNER="fde"
PGVECTOR=""
POST_ARGS=()

usage() {
  sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'
}

log() { echo "init: $*" >&2; }
die() { echo "init: ERROR $1" >&2; exit "${2:-1}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --profile) PROFILE="${2:?--profile needs minimo, padrao or completo}"; shift 2 ;;
    --client-pack) CLIENT_PACK="${2:?--client-pack needs a folder}"; shift 2 ;;
    --new-domain) NEW_DOMAIN="${2:?--new-domain needs a kebab-case name}"; shift 2 ;;
    --display-name) DISPLAY_NAME="${2:?--display-name needs a name}"; shift 2 ;;
    --owner) OWNER="${2:?--owner needs a team or person}"; shift 2 ;;
    --pgvector) PGVECTOR=1; shift ;;
    --admin-phone) POST_ARGS+=(--admin-phone "${2:?--admin-phone needs a phone}"); shift 2 ;;
    --admin-name) POST_ARGS+=(--admin-name "${2:?--admin-name needs a name}"); shift 2 ;;
    --skip-evals) POST_ARGS+=(--skip-evals); shift ;;
    --report) REPORT="${2:?--report needs a file}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1 (see --help)" 2 ;;
  esac
done

if [ -n "$NEW_DOMAIN" ] && [ -z "$DISPLAY_NAME" ]; then
  die "--new-domain needs --display-name" 2
fi
if [ -z "$NEW_DOMAIN" ] && [ -n "$DISPLAY_NAME" ]; then
  die "--display-name only goes with --new-domain" 2
fi

rand() {
  openssl rand -hex 24 2>/dev/null \
    || python3 -c 'import secrets; print(secrets.token_hex(24))' 2>/dev/null \
    || od -An -tx1 -N24 /dev/urandom | tr -d ' \n'
}

env_value() {
  # Valor de uma variavel do .env, sem imprimir nada no log.
  grep -E "^$1=" .env | tail -n 1 | cut -d= -f2-
}

set_env_value() {
  # Troca (ou acrescenta) uma variavel do .env sem regerar o resto; troca atomica,
  # o arquivo continua chmod 600.
  local name=$1 value=$2 tmp=".env.tmp.$$"
  (
    umask 077
    if grep -qE "^${name}=" .env; then
      sed -e "s|^${name}=.*|${name}=${value}|" .env > "$tmp"
    else
      { cat .env; echo "${name}=${value}"; } > "$tmp"
    fi
  )
  chmod 600 "$tmp"
  mv -f "$tmp" .env
}

# --- 1. configuracao --------------------------------------------------------------
case "${PROFILE:-minimo}" in
  minimo) TEMPLATE=deploy/production.env.example ;;
  padrao|completo) TEMPLATE="deploy/profiles/${PROFILE}.env.example" ;;
  *) die "unknown profile: ${PROFILE} (use minimo, padrao or completo)" 2 ;;
esac

if [ -e .env ]; then
  [ -z "$CLIENT_PACK" ] || die ".env already exists; set CLIENT_PACK_DIR in it instead of --client-pack" 2
  [ -z "$PROFILE" ] || die ".env already exists; its CONFIG_PROFILE decides the profile" 2
  log "reusing the existing .env (never regenerated)"
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
      -e "s|^OTP_DIGEST_SECRET=.*|OTP_DIGEST_SECRET=$(rand)|" \
      -e "s|^META_WHATSAPP_WEBHOOK_VERIFY_TOKEN=.*|META_WHATSAPP_WEBHOOK_VERIFY_TOKEN=$(rand)|" \
      ${CLIENT_PACK:+-e "s|^CLIENT_PACK_DIR=.*|CLIENT_PACK_DIR=${CLIENT_PACK}|"} \
      ${NEW_DOMAIN:+-e "s|^DEFAULT_DOMAIN=.*|DEFAULT_DOMAIN=${NEW_DOMAIN}|"} \
      "$TEMPLATE" > .env
  )
  chmod 600 .env
  unset DB_PASSWORD
  log "generated .env from the ${PROFILE:-minimo} profile with random private values (chmod 600); keep it out of Git and back it up"
fi

# So nomes de variavel saem no log, nunca valores.
PENDING="$(grep -v '^#' .env | grep -E '<set-(private|provider)-value>' | cut -d= -f1 | paste -sd ' ' - || true)"
if [ -n "$PENDING" ]; then
  die "fill every <set-private-value> and <set-provider-value> in .env, then run again: ${PENDING}" 2
fi
PACK_DIR="$(env_value CLIENT_PACK_DIR)"
PACK_DIR="${PACK_DIR:-./domains}"
[ -d "$PACK_DIR" ] || die "client pack folder not found: $PACK_DIR" 2
if [ -n "$PGVECTOR" ] && [ -z "$(env_value OPENAI_API_KEY || true)" ]; then
  die "--pgvector needs OPENAI_API_KEY in .env for the embeddings" 2
fi

# --- 2. imagem --------------------------------------------------------------------
IMAGE="${SUPPORTFAQ_IMAGE:-$(env_value SUPPORTFAQ_IMAGE || true)}"
if [ -n "$IMAGE" ]; then
  log "using published image ${IMAGE}"
  "${COMPOSE[@]}" pull app
else
  log "building the image from this checkout"
  "${COMPOSE[@]}" build app
fi

# --- 3. primeiro dominio ----------------------------------------------------------
if [ -n "$NEW_DOMAIN" ]; then
  if [ -e "${PACK_DIR}/${NEW_DOMAIN}" ]; then
    log "domain ${NEW_DOMAIN} already exists in the client pack; left untouched"
  else
    # O pacote entra read-only no app; so este comando o monta com escrita, com o
    # usuario do host, para os arquivos gerados serem de quem instala.
    PACK_ABS="$(cd "$PACK_DIR" && { pwd -W 2>/dev/null || pwd; })"
    MSYS_NO_PATHCONV=1 "${COMPOSE[@]}" run --rm --no-deps -T \
      --user "$(id -u):$(id -g)" \
      -v "${PACK_ABS}:/srv/client-pack-rw" \
      app python -m scripts.new_domain "$NEW_DOMAIN" \
      --display-name "$DISPLAY_NAME" --owner "$OWNER" \
      --domains-path /srv/client-pack-rw >&2 \
      || die "could not create domain ${NEW_DOMAIN}; nothing was written to the client pack" 2
    log "created domain ${NEW_DOMAIN}; fill its TODO(FDE) items and knowledge, then run again with --pgvector"
  fi
  if [ "$(env_value DEFAULT_DOMAIN || true)" != "$NEW_DOMAIN" ]; then
    log "DEFAULT_DOMAIN in .env is not ${NEW_DOMAIN}; change it there if this domain should answer by default"
  fi
fi

# --- 4. validar e subir -----------------------------------------------------------
# O .env entra pela entrada padrao; a saida so tem nomes e motivos.
CONFIG_TMP="${REPORT}.tmp.config"
set +e
"${COMPOSE[@]}" run --rm --no-deps -T app python -m scripts.config_validate --env-file - < .env > "$CONFIG_TMP"
CONFIG_STATUS=$?
set -e
cat "$CONFIG_TMP" >&2
if [ "$CONFIG_STATUS" -ne 0 ]; then
  rm -f "$CONFIG_TMP"
  die "the configuration is invalid; fix the errors above and run again" 2
fi

up_app() {
  "${COMPOSE[@]}" up -d --wait --wait-timeout 300 --no-build "$@"
}

if ! up_app; then
  "${COMPOSE[@]}" logs --tail 40 app >&2 || true
  die "the stack did not become healthy; the safe_start lines above say why"
fi
log "stack is up and passed readiness"

# --- 5. busca vetorial (pgvector) -------------------------------------------------
INGEST_TMP="${REPORT}.tmp.ingest"
INGEST_STATUS=0
: > "$INGEST_TMP"
if [ -n "$PGVECTOR" ]; then
  log "syncing the client pack into pgvector"
  set +e
  "${COMPOSE[@]}" run --rm -T app python -m scripts.ingest_domain_pgvector --all --markdown > "$INGEST_TMP"
  INGEST_STATUS=$?
  set -e
  BACKEND="$(env_value RETRIEVAL_BACKEND || true)"
  case "$INGEST_STATUS" in
    0)
      if [ "$BACKEND" = pgvector ]; then
        log "knowledge synced; RETRIEVAL_BACKEND was already pgvector"
      else
        set_env_value RETRIEVAL_BACKEND pgvector
        if up_app app; then
          log "knowledge synced and RETRIEVAL_BACKEND switched to pgvector"
          echo "- Busca: RETRIEVAL_BACKEND trocado para \`pgvector\` e aceito pelo readiness." >> "$INGEST_TMP"
        else
          "${COMPOSE[@]}" logs --tail 40 app >&2 || true
          set_env_value RETRIEVAL_BACKEND "${BACKEND:-lexical}"
          up_app app || die "the app did not come back after reverting RETRIEVAL_BACKEND; see the logs above"
          log "readiness refused pgvector; RETRIEVAL_BACKEND is back to ${BACKEND:-lexical}"
          echo "- Busca: o readiness recusou \`pgvector\`; RETRIEVAL_BACKEND voltou para \`${BACKEND:-lexical}\`." >> "$INGEST_TMP"
          INGEST_STATUS=1
        fi
      fi
      ;;
    3)
      log "the default domain has no knowledge yet; RETRIEVAL_BACKEND stays ${BACKEND:-lexical}"
      echo "- Busca: continua \`${BACKEND:-lexical}\` ate o dominio padrao ter conteudo." >> "$INGEST_TMP"
      INGEST_STATUS=0
      ;;
    *)
      log "pgvector sync failed; RETRIEVAL_BACKEND stays ${BACKEND:-lexical}"
      if [ ! -s "$INGEST_TMP" ]; then
        printf '## Busca vetorial (pgvector)\n\n- Resultado: ❌ a sincronizacao nao rodou (ver a saida do install.sh)\n' > "$INGEST_TMP"
      fi
      echo "- Busca: continua \`${BACKEND:-lexical}\`; corrija o erro e rode de novo com --pgvector." >> "$INGEST_TMP"
      ;;
  esac
  echo >> "$INGEST_TMP"
fi

# --- 6. pos-instalacao no container -----------------------------------------------
REPORT_TMP="${REPORT}.tmp"
set +e
"${COMPOSE[@]}" run --rm -T app python -m scripts.post_install ${POST_ARGS[@]+"${POST_ARGS[@]}"} > "$REPORT_TMP"
POST_STATUS=$?
set -e
if [ "$POST_STATUS" -eq 2 ]; then
  rm -f "$REPORT_TMP" "$CONFIG_TMP" "$INGEST_TMP"
  die "post-install rejected the arguments or the configuration" 2
fi

# --- 7. smoke HTTP ----------------------------------------------------------------
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
  echo "## Configuracao (config validate)"
  echo
  echo '```text'
  cat "$CONFIG_TMP"
  echo '```'
  echo
} > "${REPORT_TMP}.smoke"
unset API_KEY
# shellcheck disable=SC2015
grep -q '❌' "${REPORT_TMP}.smoke" && SMOKE_STATUS=1 || true

cat "$REPORT_TMP" "$INGEST_TMP" "${REPORT_TMP}.smoke" > "$REPORT"
rm -f "$REPORT_TMP" "${REPORT_TMP}.smoke" "$CONFIG_TMP" "$INGEST_TMP"

STATUS=$POST_STATUS
[ "$SMOKE_STATUS" -eq 0 ] || STATUS=1
if [ "$INGEST_STATUS" -ne 0 ] && [ "$STATUS" -ne 1 ]; then
  STATUS=$INGEST_STATUS
fi
case "$STATUS" in
  0) log "installation complete; report: $REPORT" ;;
  2) log "installed, but the pgvector sync needs configuration; report: $REPORT" ;;
  3) log "installed, but some evals failed; report: $REPORT" ;;
  *) log "installation incomplete; report: $REPORT" ;;
esac
exit "$STATUS"
