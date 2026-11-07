#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OVERRIDE_PROJECT_ID="${APPSECGATE_PROJECT_ID:-}"
OVERRIDE_MASTER_API_KEY="${APPSECGATE_MASTER_API_KEY:-}"
OVERRIDE_MASTER_URL="${APPSECGATE_MASTER_URL:-}"
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
if [[ -n "${OVERRIDE_PROJECT_ID}" ]]; then
  export APPSECGATE_PROJECT_ID="${OVERRIDE_PROJECT_ID}"
fi
if [[ -n "${OVERRIDE_MASTER_API_KEY}" ]]; then
  export APPSECGATE_MASTER_API_KEY="${OVERRIDE_MASTER_API_KEY}"
fi
if [[ -n "${OVERRIDE_MASTER_URL}" ]]; then
  export APPSECGATE_MASTER_URL="${OVERRIDE_MASTER_URL}"
fi

PROJECT="${PROJECT:-${ROOT}/repos/pygoat}"
RUN_ID="${RUN_ID:?RUN_ID is required}"
DATA_DIR="${DATA_DIR:?DATA_DIR is required}"
ARTIFACT_DIR="${ARTIFACT_DIR:-${ROOT}/artifacts/${RUN_ID}}"
CACHE_DIR="${CACHE_DIR:-${ROOT}/runtime/shared-cache}"
LLM_API_KEY="${APPSECGATE_LLM_API_KEY:-${LITELLM_API_KEY:-}}"
mkdir -p "${DATA_DIR}" "${CACHE_DIR}/trivy-cache" "${CACHE_DIR}/semgrep-cache" "${ARTIFACT_DIR}"

DOCKER_RULES_ARGS=()
if [[ "${RESEARCH_SEMGREP_RULES:-0}" == "1" ]]; then
  RESEARCH_RULES_DIR="${ROOT}/runtime/research-rules/rules"
  if [[ ! -f "${RESEARCH_RULES_DIR}/manifest.yaml" || ! -f "${RESEARCH_RULES_DIR}/.external-rules.json" ]]; then
    printf '%s\n' "Research rules are missing; run make experiment-semgrep-rules-prepare" >&2
    exit 2
  fi
  DOCKER_RULES_ARGS+=(
    -v "${RESEARCH_RULES_DIR}:/home/appsecgate/.appsecgate-mcp/rules:ro"
    -e APPSECGATE_RULES_DISTRIBUTION_MODE=commercial
  )
fi

set +e
timeout --signal=TERM --kill-after=30s "${APPSECGATE_RUN_WALL_TIMEOUT:-130m}" docker run --rm \
  --name "appsecgate-${RUN_ID}" --read-only --cap-drop=ALL --tmpfs /tmp:size=100M \
  --network "${DOCKER_NETWORK:-appsecgate-mcp_appsecgate}" \
  --add-host=host.docker.internal:host-gateway \
  -e APPSECGATE_LLM_URL="${APPSECGATE_LLM_URL:-http://10.0.0.222:4000/v1}" \
  -e APPSECGATE_SCANNER_TIMEOUT="${APPSECGATE_SCANNER_TIMEOUT:-900}" \
  -e APPSECGATE_LLM_API_KEY="${LLM_API_KEY}" \
  -e APPSECGATE_LLM_TIMEOUT="${APPSECGATE_LLM_TIMEOUT:-600}" \
  -e APPSECGATE_LLM_MODEL="${APPSECGATE_LLM_MODEL:?APPSECGATE_LLM_MODEL is required}" \
  -e APPSECGATE_LLM_TEMPERATURE="${APPSECGATE_LLM_TEMPERATURE:-0}" \
  -e APPSECGATE_LLM_TOP_P="${APPSECGATE_LLM_TOP_P:-1}" \
  -e APPSECGATE_LLM_MAX_TOKENS="${APPSECGATE_LLM_MAX_TOKENS:-2048}" \
  -e APPSECGATE_LLM_NUM_CTX="${APPSECGATE_LLM_NUM_CTX:-32768}" \
  -e APPSECGATE_AGENT_TIMEOUT="${APPSECGATE_AGENT_TIMEOUT:-7200}" \
  -e APPSECGATE_AGENT_MAX_ITERATIONS="${APPSECGATE_AGENT_MAX_ITERATIONS:-50}" \
  -e APPSECGATE_AGENT_MAX_RESTARTS="${APPSECGATE_AGENT_MAX_RESTARTS:-3}" \
  -e APPSECGATE_AGENT_MAX_COMPACTIONS="${APPSECGATE_AGENT_MAX_COMPACTIONS:-5}" \
  -e APPSECGATE_AGENT_MAX_TOKENS="${APPSECGATE_AGENT_MAX_TOKENS:-500000}" \
  -e APPSECGATE_AGENT_MAX_CONTEXT_CHARS="${APPSECGATE_AGENT_MAX_CONTEXT_CHARS:-120000}" \
  -e APPSECGATE_AGENT_MODE="${APPSECGATE_AGENT_MODE:-guided}" \
  -e APPSECGATE_AGENT_INTERNAL_PARALLEL="${APPSECGATE_AGENT_INTERNAL_PARALLEL:-2}" \
  -e APPSECGATE_AGENT_BATCH_SORT="${APPSECGATE_AGENT_BATCH_SORT:-mode_major}" \
  -e APPSECGATE_AGENT_REUSE_VERDICTS="${APPSECGATE_AGENT_REUSE_VERDICTS:-1}" \
  -e APPSECGATE_AGENT_REUSE_TTL="${APPSECGATE_AGENT_REUSE_TTL:-1w}" \
  -e APPSECGATE_MASTER_URL="${APPSECGATE_MASTER_URL:-http://appsecgate-master:8000}" \
  -e APPSECGATE_MASTER_API_KEY="${APPSECGATE_MASTER_API_KEY}" \
  -e APPSECGATE_NO_MASTER_KNOWLEDGE="${APPSECGATE_NO_MASTER_KNOWLEDGE:-0}" \
  -e APPSECGATE_KNOWLEDGE_CUTOFF="${APPSECGATE_KNOWLEDGE_CUTOFF:-}" \
  -e APPSECGATE_SYNC_OUTBOX=/home/appsecgate/.appsecgate-mcp/sync/outbox.ndjson \
  -e TRIVY_CACHE_DIR=/home/appsecgate/.cache/trivy \
  -v "${PROJECT}:/workspace:ro" \
  -v "${DATA_DIR}:/home/appsecgate/.appsecgate-mcp:rw" \
  -v "${CACHE_DIR}/trivy-cache:/home/appsecgate/.cache/trivy:rw" \
  -v "${CACHE_DIR}/semgrep-cache:/home/appsecgate/.cache/semgrep:rw" \
  "${DOCKER_RULES_ARGS[@]}" \
  moondoom/appsecgate-mcp:0.1.0 \
  agent --mode=ro --scan=full --policy="${POLICY:-warn}" --output-format=json \
  --project=/workspace --project-id="${APPSECGATE_PROJECT_ID:-pygoat-tp0001}" \
  --data-dir=/home/appsecgate/.appsecgate-mcp --run-id="${RUN_ID}" \
  --timeout="${APPSECGATE_AGENT_TIMEOUT:-7200}" --llm-timeout="${APPSECGATE_LLM_TIMEOUT:-600}" ${NO_SYNC:+--no-sync} \
  >"${ARTIFACT_DIR}/report.json" 2>"${ARTIFACT_DIR}/agent.log"
status=$?
set -e
if [[ ! -s "${ARTIFACT_DIR}/report.json" ]]; then
  python - "${RUN_ID}" "${status}" "${APPSECGATE_LLM_MODEL}" "${ARTIFACT_DIR}/report.json" <<'PY'
import json, sys
run_id, status, model, path = sys.argv[1:]
report = {
    "run_id": run_id,
    "mode": "ro",
    "model": model,
    "exit_reason": "timeout" if status == "124" else "infrastructure_error",
    "error": f"agent container exited with status {status} before report generation",
}
with open(path, "w", encoding="utf-8") as output:
    json.dump(report, output, ensure_ascii=False)
PY
fi
printf '%s\n' "${status}" >"${ARTIFACT_DIR}/exit_code"
exit "${status}"
