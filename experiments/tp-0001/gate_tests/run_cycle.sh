#!/usr/bin/env bash
set -euo pipefail

MODEL="${1:?model label is required}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "${ROOT}/../.." && pwd)"
export APPSECGATE_LLM_URL="${APPSECGATE_LLM_URL:-http://host.docker.internal:4001/v1}"
export APPSECGATE_LLM_MODEL="${APPSECGATE_LLM_MODEL:-mock-gate}"

lookup_key() {
  LOOKUP_PROJECT="$1" python -c 'import json,os; print(json.loads(os.environ["APPSECGATE_MASTER_API_KEYS"])[os.environ["LOOKUP_PROJECT"]])'
}

run_case() {
  local name="$1" project_id="$2"
  local data_dir="${ROOT}/runtime/data-${name}"
  local key
  key="$(lookup_key "${project_id}")"
  RUN_ID="${name}" DATA_DIR="${data_dir}" PROJECT="${PROJECT:-${ROOT}/repos/gate_project}" \
    APPSECGATE_PROJECT_ID="${project_id}" APPSECGATE_MASTER_API_KEY="${key}" \
    POLICY="${POLICY:-warn}" "${ROOT}/invoke-docker.sh"
}

post_event() {
  local project_id="$1" event="$2" key
  key="$(lookup_key "${project_id}")"
  python - "$project_id" "$key" "$event" <<'PY'
import json, sys, urllib.request, uuid
project, key, event = sys.argv[1:]
payload = json.loads(event)
payload.update(project_key=project, client_event_id=str(uuid.uuid4()))
request = urllib.request.Request(
    "http://127.0.0.1:8000/v1/events",
    data=json.dumps({"events": [payload]}).encode(),
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
)
with urllib.request.urlopen(request, timeout=30) as response:
    response.read()
PY
}

suppress_local() {
  local data_dir="$1" project_id="$2"
  python - "$data_dir/shown_findings.db" "$project_id" <<'PY'
import sqlite3, sys
path, project = sys.argv[1:]
db = sqlite3.connect(path)
db.execute("insert or replace into suppressions select project_id,fingerprint,'TP-0001 fixture','ci',null,last_shown_at from shown_findings where project_id=?", (project,))
db.commit()
PY
}

for test in ${TESTS:-t01 t02 t03 t04 t05 t06 t07 t08}; do
  project_id="pygoat-tp0001-${GATE_PREFIX:-gate05}-${MODEL}-${test}"
  case "${test}" in
    t01)
      post_event "${project_id}" '{"client_event_id":"00000000-0000-4000-8000-000000000011","event_type":"config_policy","at":"2026-11-02T00:00:00Z","policy":{"gates":{"ci":{"block_on":[],"warn_on":[]}}}}'
      run_case "${GATE_PREFIX:-gate05}-${MODEL}-t01a" "${project_id}"
      RUN_ID="${GATE_PREFIX:-gate05}-${MODEL}-t01b" DATA_DIR="${ROOT}/runtime/data-${GATE_PREFIX:-gate05}-${MODEL}-t01a" \
        PROJECT="${ROOT}/repos/gate_project" APPSECGATE_PROJECT_ID="${project_id}" \
        APPSECGATE_MASTER_API_KEY="$(lookup_key "${project_id}")" "${ROOT}/invoke-docker.sh"
      ;;
    t02)
      run_case "${GATE_PREFIX:-gate05}-${MODEL}-t02a" "${project_id}"
      suppress_local "${ROOT}/runtime/data-${GATE_PREFIX:-gate05}-${MODEL}-t02a" "${project_id}"
      RUN_ID="${GATE_PREFIX:-gate05}-${MODEL}-t02b" DATA_DIR="${ROOT}/runtime/data-${GATE_PREFIX:-gate05}-${MODEL}-t02a" \
        PROJECT="${ROOT}/repos/gate_project" APPSECGATE_PROJECT_ID="${project_id}" \
        APPSECGATE_MASTER_API_KEY="$(lookup_key "${project_id}")" "${ROOT}/invoke-docker.sh"
      ;;
    t03)
      post_event "${project_id}" '{"client_event_id":"00000000-0000-4000-8000-000000000031","event_type":"config_policy","at":"2026-11-02T00:00:00Z","policy":{"gates":{"ci":{"block_on":[],"warn_on":[],"block_on_unresolved_local":false}}}}'
      run_case "${GATE_PREFIX:-gate05}-${MODEL}-t03a" "${project_id}"
      patched="${ROOT}/runtime/${GATE_PREFIX:-gate05}-${MODEL}-t03-patched"
      mkdir -p "${patched}"
      cp "${ROOT}/repos/gate_project/requirements.txt" "${patched}/requirements.txt"
      python - "${patched}/requirements.txt" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
path.write_text(path.read_text().replace("django==3.2.18", "django==5.2.8"))
PY
      RUN_ID="${GATE_PREFIX:-gate05}-${MODEL}-t03b" DATA_DIR="${ROOT}/runtime/data-${GATE_PREFIX:-gate05}-${MODEL}-t03a" \
        PROJECT="${patched}" APPSECGATE_PROJECT_ID="${project_id}" \
        APPSECGATE_MASTER_API_KEY="$(lookup_key "${project_id}")" "${ROOT}/invoke-docker.sh"
      ;;
    t04)
      RUN_ID="${GATE_PREFIX:-gate05}-${MODEL}-t04" DATA_DIR="${ROOT}/runtime/data-${GATE_PREFIX:-gate05}-${MODEL}-t04" \
        APPSECGATE_PROJECT_ID="${project_id}" APPSECGATE_MASTER_API_KEY="$(lookup_key "${project_id}")" \
        APPSECGATE_MASTER_URL="http://127.0.0.1:9" "${ROOT}/invoke-docker.sh" || test "$?" = 2
      ;;
    t05)
      run_case "${GATE_PREFIX:-gate05}-${MODEL}-t05a" "${project_id}"
      post_event "${project_id}" '{"client_event_id":"00000000-0000-4000-8000-000000000051","event_type":"config_policy","at":"2026-11-02T00:00:00Z","policy":{"gates":{"ci":{"block_on":[],"warn_on":[],"block_on_unresolved_local":false}}}}'
      APPSECGATE_MASTER_API_KEY="$(lookup_key "${project_id}")" "${REPO_ROOT}/mcp-server/.venv/bin/appsecgate-mcp" sync \
        --data-dir "${ROOT}/runtime/data-${GATE_PREFIX:-gate05}-${MODEL}-t05a" --project-id "${project_id}" \
        --master-url http://127.0.0.1:8000
      RUN_ID="${GATE_PREFIX:-gate05}-${MODEL}-t05b" DATA_DIR="${ROOT}/runtime/data-${GATE_PREFIX:-gate05}-${MODEL}-t05a" \
        PROJECT="${ROOT}/repos/gate_project" APPSECGATE_PROJECT_ID="${project_id}" \
        APPSECGATE_MASTER_API_KEY="$(lookup_key "${project_id}")" "${ROOT}/invoke-docker.sh"
      ;;
    t06)
      run_case "${GATE_PREFIX:-gate05}-${MODEL}-t06a" "${project_id}"
      index=0
      while read -r fp; do
        index=$((index + 1))
        event_id="$(printf '00000000-0000-4000-8000-%012d' "${index}")"
        post_event "${project_id}" "{\"client_event_id\":\"${event_id}\",\"event_type\":\"suppressed\",\"at\":\"2026-11-03T00:00:01Z\",\"fp\":\"${fp}\",\"scope\":\"ci\",\"reason\":\"TP-0001 fixture\"}"
      done < <(python -c 'import json; print("\n".join(x["finding_id"] for x in json.load(open("'"${ROOT}"'/artifacts/'"${GATE_PREFIX:-gate05}"'-'"${MODEL}"'-t06a/report.json"))["findings"]))')
      APPSECGATE_MASTER_API_KEY="$(lookup_key "${project_id}")" "${REPO_ROOT}/mcp-server/.venv/bin/appsecgate-mcp" sync \
        --data-dir "${ROOT}/runtime/data-${GATE_PREFIX:-gate05}-${MODEL}-t06a" --project-id "${project_id}" \
        --master-url http://127.0.0.1:8000
      RUN_ID="${GATE_PREFIX:-gate05}-${MODEL}-t06b" DATA_DIR="${ROOT}/runtime/data-${GATE_PREFIX:-gate05}-${MODEL}-t06a" \
        PROJECT="${ROOT}/repos/gate_project" APPSECGATE_PROJECT_ID="${project_id}" \
        APPSECGATE_MASTER_API_KEY="$(lookup_key "${project_id}")" "${ROOT}/invoke-docker.sh"
      ;;
    t07)
      run_case "${GATE_PREFIX:-gate05}-${MODEL}-t07" "${project_id}"
      RUN_ID="${GATE_PREFIX:-gate05}-${MODEL}-t07" DATA_DIR="${ROOT}/runtime/data-${GATE_PREFIX:-gate05}-${MODEL}-t07" \
        PROJECT="${ROOT}/repos/gate_project" APPSECGATE_PROJECT_ID="${project_id}" \
        APPSECGATE_MASTER_API_KEY="$(lookup_key "${project_id}")" \
        "${ROOT}/invoke-docker.sh"
      ;;
    t08)
      POLICY=block run_case "${GATE_PREFIX:-gate05}-${MODEL}-t08" "${project_id}"
      ;;
  esac
done
