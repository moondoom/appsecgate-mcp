# syntax=docker/dockerfile:1
#
# AppSecGate MCP — multi-stage образ.
# non-root (1000:1000), read-only rootfs friendly, без docker.sock.
#
# Порядок слоёв runtime выстроен от стабильных к изменяемым:
#   base → apt+user → tools → trivy-db → venv → rules → config/entrypoint.
# Это гарантирует, что правка кода проекта (venv/rules) НЕ сбрасывает кэш
# тяжёлого слоя с Trivy DB (~1.6 GB) — он зависит только от стадии tools.

# ----------------------------------------------------------------------
# Stage: build-deps — только загрузка tarball'ов инструментов
# (отдельный слой, чтобы распаковка в tools не включала curl/ca-certificates)
# ----------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS build-deps

ENV DEBIAN_FRONTEND=noninteractive

# Библиотеки CA + curl нужны ТОЛЬКО для загрузки; в tools/runtime не попадают.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl

WORKDIR /tmp/download
ARG GITLEAKS_VERSION=8.21.2
ARG TRUFFLEHOG_VERSION=3.82.13
ARG TRIVY_VERSION=0.75.0
# Каждый инструмент именует архитектуры по-своему (значения для amd64).
ARG GITLEAKS_ARCH=x64
ARG TRUFFLEHOG_ARCH=amd64
ARG TRIVY_ARCH=64bit

RUN curl -fsSL -o gitleaks.tar.gz \
        "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_${GITLEAKS_ARCH}.tar.gz" \
 && curl -fsSL -o trufflehog.tar.gz \
        "https://github.com/trufflesecurity/trufflehog/releases/download/v${TRUFFLEHOG_VERSION}/trufflehog_${TRUFFLEHOG_VERSION}_linux_${TRUFFLEHOG_ARCH}.tar.gz" \
 && curl -fsSL -o trivy.tar.gz \
        "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-${TRIVY_ARCH}.tar.gz"

# ----------------------------------------------------------------------
# Stage: tools — распаковка бинарников и загрузка Trivy DB
# ----------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS tools

COPY --from=build-deps /tmp/download/ /tmp/download/

# Бинарники инструментов в одном слое: gitleaks/trufflehog статические,
# trivy собран на cgo → требует glibc (есть в базовом образе).
RUN tar -xzf /tmp/download/gitleaks.tar.gz -C /usr/local/bin gitleaks \
 && tar -xzf /tmp/download/trufflehog.tar.gz -C /usr/local/bin trufflehog \
 && tar -xzf /tmp/download/trivy.tar.gz -C /usr/local/bin trivy \
 && rm -rf /tmp/download

ARG WITH_JAVA_DB=false
# Seed Trivy DB на этапе сборки: при первом запуске entrypoint копирует её
# в TRIVY_CACHE_DIR. WITH_JAVA_DB=true добавляет Java DB (артефакты Maven/Gradle).
# Стадия зависит ТОЛЬКО от бинарника trivy, поэтому правка кода проекта
# не инвалидирует этот слой и не перекачивает ~1.6 GB.
RUN trivy image --cache-dir /opt/appsecgate/trivy-db-seed --download-db-only \
 && if [ "$WITH_JAVA_DB" = "true" ]; then \
      trivy image --cache-dir /opt/appsecgate/trivy-db-seed --download-java-db-only; \
    fi

# ----------------------------------------------------------------------
# Stage: builder — собираем Python venv через uv
# ----------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/appsecgate-venv

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/

WORKDIR /build
COPY pyproject.toml README.md ./

# Устанавливаем только runtime-зависимости в изолированный venv.
# Кэш uv живёт в BuildKit cache mount, а не в слое.
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv venv /opt/appsecgate-venv && \
    uv pip install --python /opt/appsecgate-venv/bin/python --no-compile \
        'mcp>=1.2.0,<2' 'pydantic>=2.7' 'PyYAML>=6.0' semgrep

COPY src ./src
# Пакет приложения ставится из корня проекта (там pyproject.toml); --no-deps —
# зависимости уже установлены выше. Hatchling (build backend) берётся из uv-кэша.
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv pip install --python /opt/appsecgate-venv/bin/python --no-compile --no-deps .

# Strip vendor docs/metadata and __pycache__ from installed packages.
# Removes false-positive sources (doctest examples in METADATA, e.g., pyjwt JWT token)
# and reduces image size. Keep our own .dist-info for FastMCP version resolution.
RUN find /opt/appsecgate-venv/lib/python3.12/site-packages \
        -type d -name '*.dist-info' \
        ! -name 'appsecgate_mcp*' \
        ! -name 'mcp*' \
        -prune -exec rm -rf {} + \
    && find /opt/appsecgate-venv -type d -name '__pycache__' -prune -exec rm -rf {} + \
    && PYTHONDONTWRITEBYTECODE=1 /opt/appsecgate-venv/bin/python -c "import appsecgate_mcp.server; from mcp.server.fastmcp import FastMCP; FastMCP('t'); import semgrep; print('smoke: ok')"
# ----------------------------------------------------------------------
# Stage: runtime — сканеры + venv (слои ниже стабильны относительно кода)
# ----------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/home/appsecgate \
    PATH="/opt/appsecgate-venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TRIVY_CACHE_DIR=/home/appsecgate/.cache/trivy \
    APPSECGATE_MCP_HOME=/home/appsecgate/.appsecgate-mcp \
    SEMGREP_SETTINGS_FILE=/home/appsecgate/.cache/semgrep/settings.yml \
    SEMGREP_VERSION_CACHE_PATH=/home/appsecgate/.cache/semgrep/version \
    SEMGREP_LOG_FILE=/tmp/semgrep.log

# Runtime нужны ТОЛЬКО ca-certificates + git (semgrep --baseline, см. scanners/semgrep.py).
# curl/gnupg/tar отсутствуют: скачивание идёт на стадии build, обновления — нет.
# Кэш apt живёт в BuildKit cache mount и в слой не попадает.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates git \
 && rm -rf /var/lib/apt/lists/*

# non-root пользователь 1000:1000
RUN groupadd --gid 1000 appsecgate \
    && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/appsecgate --shell /usr/sbin/nologin appsecgate \
    && mkdir -p /home/appsecgate/.cache /home/appsecgate/.semgrep /home/appsecgate/.appsecgate-mcp /workspace \
    && chown -R 1000:1000 /home/appsecgate /workspace

# Бинарники сканеров из стадии tools.
# --chmod добавляет права в том же слое COPY → без дубля слоя (в отличие от RUN chmod).
COPY --chmod=a+rX --from=tools /usr/local/bin/gitleaks /usr/local/bin/trufflehog /usr/local/bin/trivy /usr/local/bin/

# Seed Trivy DB — слой ~1.6 GB. Изолирован от venv/rules: правка кода
# пересобирает только нижележащие слои, БД остаётся в кэше BuildKit.
# --chmod (a+rX) вместо RUN chmod -R — иначе copy-up дублировал бы файл.
COPY --chmod=a+rX --from=tools /opt/appsecgate/trivy-db-seed /opt/appsecgate/trivy-db-seed

# Semgrep (pip image) — самодостаточный бинарник в venv.
COPY --chmod=a+rX --from=builder /opt/appsecgate-venv /opt/appsecgate-venv

# Bundle правил сканеров (атомарная единица, см. mcp-server/rules/manifest.yaml).
COPY --chmod=a+rX rules/ /opt/appsecgate/rules/

LABEL io.modelcontextprotocol.server.name="io.github.moondoom/appsecgate-mcp"

# Конфиг по умолчанию
COPY config/default.yaml /etc/appsecgate/default.yaml

# Entrypoint: seed-on-first-run Trivy DB, затем exec "$@" (см. scripts/entrypoint.sh).
# COPY --chmod=0755 — один слой вместо COPY + RUN chmod.
COPY --chmod=0755 scripts/entrypoint.sh /usr/local/bin/appsecgate-entrypoint.sh

USER 1000:1000
WORKDIR /workspace

# Обновление баз сканеров — только на этапе сборки/через volume.
# Сканеры проверяются адаптерами через is_available(); отсутствие — не фатально.

ENTRYPOINT ["/usr/local/bin/appsecgate-entrypoint.sh", "appsecgate-mcp"]
CMD ["--transport", "stdio"]
