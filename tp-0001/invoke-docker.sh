#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${ROOT}/../.env" ]]; then
  set -a
  source "${ROOT}/../.env"
  set +a
fi
if [[ -f "${ROOT}/runtime/master.env" ]]; then
  set -a
  source "${ROOT}/runtime/master.env"
  set +a
fi

PROJECT="${PROJECT:-${ROOT}/repos/pygoat}"
RUN_ID="${RUN_ID:?RUN_ID is required}"
DATA_DIR="${DATA_DIR:?DATA_DIR is required}"
ARTIFACT_DIR="${ARTIFACT_DIR:-${ROOT}/artifacts/${RUN_ID}}"
LLM_API_KEY="${APPSECGATE_LLM_API_KEY:-${LITELLM_API_KEY:-}}"
mkdir -p "${DATA_DIR}/trivy-cache" "${DATA_DIR}/semgrep-cache" "${ARTIFACT_DIR}"

set +e
timeout --signal=TERM --kill-after=30s 35m docker run --rm \
  --name "appsecgate-${RUN_ID}" --read-only --cap-drop=ALL --tmpfs /tmp:size=100M \
  --network appsecgate-mcp_appsecgate \
  --add-host=host.docker.internal:host-gateway \
  -e APPSECGATE_LLM_URL="${APPSECGATE_LLM_URL:-http://10.0.0.222:4000/v1}" \
  -e APPSECGATE_LLM_API_KEY="${LLM_API_KEY}" \
  -e APPSECGATE_LLM_MODEL="${APPSECGATE_LLM_MODEL:?APPSECGATE_LLM_MODEL is required}" \
  -e APPSECGATE_MASTER_URL="${APPSECGATE_MASTER_URL:-http://appsecgate-master:8000}" \
  -e APPSECGATE_MASTER_API_KEY="${APPSECGATE_MASTER_API_KEY}" \
  -e APPSECGATE_SYNC_OUTBOX=/home/appsecgate/.appsecgate-mcp/sync/outbox.ndjson \
  -e TRIVY_CACHE_DIR=/home/appsecgate/.cache/trivy \
  -v "${PROJECT}:/workspace:ro" \
  -v "${DATA_DIR}:/home/appsecgate/.appsecgate-mcp:rw" \
  -v "${DATA_DIR}/trivy-cache:/home/appsecgate/.cache/trivy:rw" \
  -v "${DATA_DIR}/semgrep-cache:/home/appsecgate/.cache/semgrep:rw" \
  moondoom/appsecgate-mcp:0.1.0 \
  agent --mode=ro --scan=full --policy=warn --output-format=json \
  --project=/workspace --project-id="${APPSECGATE_PROJECT_ID:-pygoat-tp0001}" \
  --data-dir=/home/appsecgate/.appsecgate-mcp --run-id="${RUN_ID}" \
  --timeout=1800 --llm-timeout=300 \
  >"${ARTIFACT_DIR}/report.json" 2>"${ARTIFACT_DIR}/agent.log"
status=$?
set -e
printf '%s\n' "${status}" >"${ARTIFACT_DIR}/exit_code"
exit "${status}"
