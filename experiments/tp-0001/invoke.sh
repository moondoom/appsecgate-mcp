#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${ROOT}/../../.env" ]]; then
  set -a
  source "${ROOT}/../../.env"
  set +a
fi
if [[ -f "${ROOT}/runtime/master.env" ]]; then
  set -a
  source "${ROOT}/runtime/master.env"
  set +a
fi
export APPSECGATE_LLM_URL="${APPSECGATE_LLM_URL:-http://10.0.0.222:4000/v1}"
export APPSECGATE_LLM_API_KEY="${APPSECGATE_LLM_API_KEY:-${LITELLM_API_KEY:-}}"
export APPSECGATE_RULES_PATH="${APPSECGATE_RULES_PATH:-${ROOT}/../../mcp-server/rules}"
PROJECT="${PROJECT:-${ROOT}/repos/pygoat}"
APPSECGATE_BIN="${APPSECGATE_BIN:-${ROOT}/../../mcp-server/.venv/bin/appsecgate-mcp}"
RUN_ID="${RUN_ID:?RUN_ID is required}"
DATA_DIR="${DATA_DIR:?DATA_DIR is required}"
ARTIFACT_DIR="${ARTIFACT_DIR:-${ROOT}/artifacts/${RUN_ID}}"
mkdir -p "${DATA_DIR}" "${ARTIFACT_DIR}"

set +e
timeout --signal=TERM --kill-after=30s 35m "${APPSECGATE_BIN}" agent \
  --mode=ro --scan=full --policy=warn --output-format=json \
  --project="${PROJECT}" --project-id="${PROJECT_ID:-pygoat-tp0001}" \
  --data-dir="${DATA_DIR}" --run-id="${RUN_ID}" \
  --timeout=1800 --llm-timeout=120 \
  >"${ARTIFACT_DIR}/report.json" 2>"${ARTIFACT_DIR}/agent.log"
status=$?
set -e
printf '%s\n' "${status}" >"${ARTIFACT_DIR}/exit_code"
exit "${status}"
