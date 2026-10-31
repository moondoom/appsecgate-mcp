# syntax=docker/dockerfile:1
#
# AppSecGate Master — Docker-образ (Фаза 2, MS-7).
# non-root (1000:1000), read-only rootfs friendly, cap_drop ALL.
# Только runtime-зависимости master (fastapi/uvicorn/pydantic), без сканеров.

# ----------------------------------------------------------------------
# Stage: builder — Python venv через uv (паттерн mcp-server/Dockerfile)
# ----------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/appsecgate-venv

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/

WORKDIR /build
COPY pyproject.toml uv.lock README.md ./

# Устанавливаем только runtime-зависимости в изолированный venv (--no-dev,
# --frozen по uv.lock). Кэш uv живёт в BuildKit cache mount, не в слое.
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev --no-install-project

COPY src ./src
# Пакет приложения ставится из корня проекта; --no-deps — зависимости выше.
# Hatchling (build backend) берётся из uv-кэша.
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv pip install --python /opt/appsecgate-venv/bin/python --no-compile --no-deps .

# ----------------------------------------------------------------------
# Stage: runtime
# ----------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/home/appsecgate \
    PATH="/opt/appsecgate-venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Runtime нужны ТОЛЬКО ca-certificates (TLS на reverse-proxy).
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# non-root пользователь 1000:1000 (тот же uid, что у mcp-образа).
RUN groupadd --gid 1000 appsecgate \
    && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/appsecgate \
        --shell /usr/sbin/nologin appsecgate \
    && mkdir -p /home/appsecgate/.appsecgate/master \
    && chown -R 1000:1000 /home/appsecgate

COPY --chmod=a+rX --from=builder /opt/appsecgate-venv /opt/appsecgate-venv

LABEL io.appsecgate.component="appsecgate-master"

USER 1000:1000
WORKDIR /home/appsecgate

EXPOSE 8000

CMD ["uvicorn", "appsecgate_master.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
