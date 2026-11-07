#!/usr/bin/env bash
# GD-6 acceptance: ACC-B (1x2), ACC-D (2x2) on atopile/costrict/CodeWiki,
# ACC-E (4x1) on atopile. Sequential arms, no interleaving (ADR-0019 §2.4).
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

export BENCH_MODELS=gemmaq3
export APPSECGATE_LLM_MODEL="ollama/hf.co/unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q3_K_M"
export APPSECGATE_LLM_NUM_CTX=36864
export APPSECGATE_LLM_FAILURE_TIMEOUT_S=600
export APPSECGATE_AGENT_REUSE_VERDICTS=0
export APPSECGATE_AGENT_BATCH_SORT=mode_major
export APPSECGATE_MASTER_URL="http://appsecgate-agent300-master:8000"
export APPSECGATE_MASTER_HOST_URL="http://127.0.0.1:8001"
export APPSECGATE_MASTER_API_KEYS="$(cat runtime/agent300-keys.json)"
export APPSECGATE_KNOWLEDGE_CUTOFF=""
export APPSECGATE_NUM_PARALLEL_MAX=4

run_arm() {
  local arm="$1" internal="$2" external="$3" projects="$4"
  echo "=== arm ${arm}: internal=${internal} external=${external} projects=${projects} ==="
  BENCH_LABEL="${arm}" BENCH_PROJECT_ID_LABEL="${arm}" \
    APPSECGATE_AGENT_INTERNAL_PARALLEL="${internal}" \
    BENCH_PARALLELISM="${external}" \
    BENCH_PROJECTS="${projects}" \
    BENCH_OUTPUT="acceptance-${arm}.json" \
    python3 benchmark_parallel.py
}

STARTED=$(date +%s)
run_arm accb 1 2 "atopile,costrict,CodeWiki"
run_arm accd 2 2 "atopile,costrict,CodeWiki"
run_arm acce 4 1 "atopile"
ELAPSED=$(( $(date +%s) - STARTED ))
echo "=== acceptance wall: ${ELAPSED}s ==="
if [ "${ELAPSED}" -gt 5400 ]; then
  echo "ABORT: acceptance exceeded 90 minute cap" >&2
  exit 3
fi
