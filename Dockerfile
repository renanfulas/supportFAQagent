# syntax=docker/dockerfile:1
#
# Imagem de producao do supportFAQagent (motor + pacote de cliente padrao).
#
# - Python 3.11: a mesma versao do runtime de producao (ver .github/workflows/ci.yml).
# - As dependencias saem do pyproject.toml, a unica fonte de verdade; nao ha
#   requirements.txt paralelo.
# - Nenhum segredo entra na imagem: o .dockerignore e uma allowlist e a
#   configuracao chega em runtime por variavel de ambiente (env_file no compose).
# - Roda como usuario nao-root, sem shell de login, com healthcheck em /health.
#
# Runbook: docs/runbooks/docker-install.md

ARG PYTHON_IMAGE=python:3.11-slim-bookworm

# --- builder: resolve as dependencias num venv isolado ---------------------------
FROM ${PYTHON_IMAGE} AS builder

# Extras opcionais do pyproject, separados por virgula (ex.: "redis,s3").
ARG EXTRAS=""

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /build
COPY pyproject.toml ./

# Le dependencies (+ extras pedidos) direto do pyproject. So o pyproject entra
# nesta camada, entao mudar codigo nao reinstala dependencias.
RUN python - <<'PY' > /tmp/requirements.txt
import os
import tomllib

with open("pyproject.toml", "rb") as handle:
    project = tomllib.load(handle)["project"]

requirements = list(project["dependencies"])
optional = project.get("optional-dependencies", {})
for extra in filter(None, (item.strip() for item in os.environ.get("EXTRAS", "").split(","))):
    if extra not in optional:
        raise SystemExit(f"unknown extra: {extra}")
    requirements.extend(optional[extra])

print("\n".join(requirements))
PY
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/requirements.txt

# --- runtime ---------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    DOMAINS_PATH=/app/domains \
    PORT=8000

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /var/lib/supportfaq \
    && chown app:app /var/lib/supportfaq

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=root:root app ./app
COPY --chown=root:root scripts ./scripts
COPY --chown=root:root migrations ./migrations
COPY --chown=root:root domains ./domains

USER app

EXPOSE 8000

# Liveness sem dependencia externa (curl nao existe na imagem slim).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'), timeout=4)"]

# 0.0.0.0 e o bind dentro do container; quem decide a exposicao e o compose
# (publica so em 127.0.0.1) e o reverse proxy na frente. FORWARDED_ALLOW_IPS
# (lido pelo uvicorn) define de quem o X-Forwarded-For e confiavel.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT}\" --no-server-header"]
