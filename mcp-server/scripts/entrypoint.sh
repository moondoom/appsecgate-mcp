#!/usr/bin/env bash
# AppSecGate MCP entrypoint: seed-on-first-run Trivy DB, затем запуск сервера.
#
# Дизайн v1 §5: rootfs read-only, поэтому seed-копия живёт в образе
# (/opt/appsecgate/trivy-db-seed), а рабочая БД — в writable named volume
# ($TRIVY_CACHE_DIR). Копируем только если БД ещё нет (идемпотентно).
# Seed-on-first-run снимает вопрос лицензирования данных: пользователь
# получает БД напрямую от Aqua, а не в составе нашего образа.
set -euo pipefail

CACHE_DIR="${TRIVY_CACHE_DIR:-/home/appsecgate/.cache/trivy}"
SEED_DIR="${APPSECGATE_TRIVY_DB_SEED:-/opt/appsecgate/trivy-db-seed}"

if [ ! -f "${CACHE_DIR}/db/trivy.db" ] && [ -d "${SEED_DIR}/db" ]; then
    mkdir -p "${CACHE_DIR}"
    cp -a "${SEED_DIR}/." "${CACHE_DIR}/"
fi

exec "$@"