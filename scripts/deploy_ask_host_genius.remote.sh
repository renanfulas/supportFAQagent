set -e

# Deploy do frontend ask-host-genius no VPS, seguindo a branch de producao.
# Branch padrao: main. Para um deploy pontual de outra branch:
#   DEPLOY_BRANCH=alguma-branch bash deploy_ask_host_genius.remote.sh
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"

APP_DIR="/opt/ask-host-genius"
if [ ! -d "$APP_DIR/.git" ]; then
  APP_DIR="$(find /opt /srv /var/www /root -maxdepth 4 -type d -name ask-host-genius 2>/dev/null | head -n 1)"
fi

if [ -z "$APP_DIR" ] || [ ! -d "$APP_DIR/.git" ]; then
  echo "ask-host-genius repo nao encontrado; clonando em /opt/ask-host-genius"
  mkdir -p /opt
  if [ -e /opt/ask-host-genius ] && [ ! -d /opt/ask-host-genius/.git ]; then
    BACKUP_DIR="/opt/ask-host-genius.backup.$(date +%Y%m%d%H%M%S)"
    echo "/opt/ask-host-genius existe sem .git; movendo para $BACKUP_DIR"
    mv /opt/ask-host-genius "$BACKUP_DIR"
  fi
  git clone https://github.com/renanfulas/ask-host-genius.git /opt/ask-host-genius
  if [ -n "${BACKUP_DIR:-}" ]; then
    find "$BACKUP_DIR" -maxdepth 1 -type f -name '.env*' -exec cp -n {} /opt/ask-host-genius/ \;
  fi
  APP_DIR="/opt/ask-host-genius"
fi

cd "$APP_DIR"

echo "== antes =="
pwd
git status --short --branch
git log -1 --oneline

# Segue a branch de producao (main). Alinha o working tree com origin/<branch>
# de forma deterministica, descartando estado local de deploys anteriores.
git fetch origin
git checkout "$DEPLOY_BRANCH"
git reset --hard "origin/$DEPLOY_BRANCH"

echo "== branch alvo =="
echo "DEPLOY_BRANCH=$DEPLOY_BRANCH"
git log -1 --oneline

if [ -f bun.lock ]; then
  if [ -f package-lock.json ] && ! git ls-files --error-unmatch package-lock.json >/dev/null 2>&1; then
    echo "package-lock.json local nao rastreado encontrado; removendo para evitar conflito com bun.lock"
    rm -f package-lock.json
  fi
  if ! command -v bun >/dev/null 2>&1; then
    if ! command -v unzip >/dev/null 2>&1; then
      echo "unzip nao encontrado; instalando unzip para instalar Bun"
      if command -v apt-get >/dev/null 2>&1; then
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y unzip
      else
        echo "Nao encontrei apt-get; instale unzip manualmente antes de instalar Bun"
        exit 1
      fi
    fi
    echo "bun nao encontrado; instalando Bun para respeitar bun.lock"
    curl -fsSL https://bun.sh/install | bash
    export BUN_INSTALL="${BUN_INSTALL:-$HOME/.bun}"
    export PATH="$BUN_INSTALL/bin:$PATH"
  fi
  bun install --frozen-lockfile
elif [ -f package-lock.json ] && git ls-files --error-unmatch package-lock.json >/dev/null 2>&1; then
  npm ci --legacy-peer-deps
else
  if [ -f package-lock.json ]; then
    echo "package-lock.json local nao rastreado encontrado; removendo para evitar lock parcial de deploy anterior"
    rm -f package-lock.json
  fi
  echo "lockfile rastreado ausente; usando npm install --legacy-peer-deps para gerar node_modules"
  npm install --legacy-peer-deps --include=dev
fi

if [ -f bun.lock ]; then
  bun run build
else
  npm run build
fi

echo "== reiniciando frontend =="
if systemctl list-unit-files | grep -q '^ask-host-genius.service'; then
  systemctl restart ask-host-genius.service
  systemctl is-active ask-host-genius.service
elif docker ps --format '{{.Names}}' | grep -q '^ask_host_genius$'; then
  if [ -f docker-compose.yml ] || [ -f compose.yml ] || [ -f docker-compose.yaml ] || [ -f compose.yaml ]; then
    docker compose up -d --build
  else
    docker restart ask_host_genius
  fi
elif docker ps --format '{{.Names}}' | grep -q 'ask'; then
  docker ps --format '{{.Names}} {{.Image}} {{.Status}}' | grep ask
  echo "Container encontrado, mas nome exato precisa ser confirmado antes de restart."
  exit 2
else
  echo "Servico/container do frontend nao encontrado"
  docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
  systemctl list-units --type=service | grep -Ei 'ask|host|genius|chat' || true
  exit 2
fi

echo "== depois =="
git log -1 --oneline
curl -fsSI http://127.0.0.1:5173/chat-ui
curl -fsSI "https://chat.ordens.com.br/chat-ui?deploy_check=$(date +%s)"
curl -fsS -H "Content-Type: application/json" -d '{"message":"Como conectar o WhatsApp pela Meta API oficial?"}' https://chat.ordens.com.br/web/chat | head -c 1200
echo

echo "== verificacao de conteudo =="
curl -fsS http://127.0.0.1:5173/chat-ui -o /tmp/chat-ui-local.html
curl -fsS "https://chat.ordens.com.br/chat-ui?deploy_check=$(date +%s)" -o /tmp/chat-ui-public.html
sha256sum /tmp/chat-ui-local.html /tmp/chat-ui-public.html
echo "-- local title/assets --"
grep -Eo '<title>[^<]+|/assets/[^"]+' /tmp/chat-ui-local.html | head -20 || true
echo "-- public title/assets --"
grep -Eo '<title>[^<]+|/assets/[^"]+' /tmp/chat-ui-public.html | head -20 || true

echo "== freshness dos assets publicos (Last-Modified deve ser de hoje) =="
PUB_ASSET="$(grep -Eo '/assets/index-[^"]+\.js' /tmp/chat-ui-public.html | head -1)"
if [ -n "$PUB_ASSET" ]; then
  curl -fsSI "https://chat.ordens.com.br${PUB_ASSET}" | grep -i -E 'last-modified|cf-cache-status' || true
fi

echo "== quem esta ouvindo 5173 =="
ss -ltnp '( sport = :5173 )' || true
ps -eo pid,ppid,cmd | grep -Ei 'vite|node|ask-host|5173' | grep -v grep || true
