# syntax=docker/dockerfile:1
#
# SecGate MCP — multi-stage образ.
# non-root (1000:1000), read-only rootfs friendly, без docker.sock.

# ----------------------------------------------------------------------
# Stage 1: builder — собираем Python venv через uv
# ----------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/secgate-venv

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src

# Устанавливаем только runtime-зависимости в изолированный venv.
RUN uv venv /opt/secgate-venv && \
    uv pip install --python /opt/secgate-venv/bin/python . semgrep

# ----------------------------------------------------------------------
# Stage 2: runtime — сканеры + venv
# ----------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ARG GITLEAKS_VERSION=8.21.2
ARG TRUFFLEHOG_VERSION=3.82.13
ARG TRIVY_VERSION=0.75.0
# Каждый инструмент именует архитектуры по-своему (значения для amd64).
ARG GITLEAKS_ARCH=x64
ARG TRUFFLEHOG_ARCH=amd64
ARG TRIVY_ARCH=64bit

ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/home/secgate \
    PATH="/opt/secgate-venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TRIVY_CACHE_DIR=/home/secgate/.cache/trivy \
    SECGATE_MCP_HOME=/home/secgate/.secgate-mcp

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git gnupg tar \
    && rm -rf /var/lib/apt/lists/*
# Semgrep (pip image) — самодостаточный бинарник в venv.
COPY --from=builder /opt/secgate-venv /opt/secgate-venv

# Gitleaks
RUN curl -fsSL -o /tmp/gitleaks.tar.gz \
        "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_${GITLEAKS_ARCH}.tar.gz" \
    && tar -xzf /tmp/gitleaks.tar.gz -C /usr/local/bin gitleaks \
    && rm /tmp/gitleaks.tar.gz

# TruffleHog
RUN curl -fsSL -o /tmp/trufflehog.tar.gz \
        "https://github.com/trufflesecurity/trufflehog/releases/download/v${TRUFFLEHOG_VERSION}/trufflehog_${TRUFFLEHOG_VERSION}_linux_${TRUFFLEHOG_ARCH}.tar.gz" \
    && tar -xzf /tmp/trufflehog.tar.gz -C /usr/local/bin trufflehog \
    && rm /tmp/trufflehog.tar.gz

# Trivy
RUN curl -fsSL -o /tmp/trivy.tar.gz \
        "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-${TRIVY_ARCH}.tar.gz" \
    && tar -xzf /tmp/trivy.tar.gz -C /usr/local/bin trivy \
    && rm /tmp/trivy.tar.gz

# non-root пользователь 1000:1000
RUN groupadd --gid 1000 secgate \
    && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/secgate --shell /usr/sbin/nologin secgate \
    && mkdir -p /home/secgate/.cache /home/secgate/.secgate-mcp /workspace \
    && chown -R 1000:1000 /home/secgate /workspace

# Конфиг по умолчанию
COPY config/default.yaml /etc/secgate/default.yaml

USER 1000:1000
WORKDIR /workspace

# Обновление баз сканеров — только на этапе сборки/через volume.
# Сканеры проверяются адаптерами через is_available(); отсутствие — не фатально.

ENTRYPOINT ["secgate-mcp"]
CMD ["--transport", "stdio"]
