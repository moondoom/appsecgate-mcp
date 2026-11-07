#!/usr/bin/env bash
# A1 + A2 same-session ablations (consolidated review 2026-11-07).
# Same image as GD-7 sweep; all cells sequential on atopile, reuse OFF.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

export BENCH_MODELS=gemmaq3
export APPSECGATE_LLM_MODEL="ollama/hf.co/unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q3_K_M"
export APPSECGATE_LLM_NUM_CTX=36864
export APPSECGATE_LLM_FAILURE_TIMEOUT_S=600
export APPSECGATE_AGENT_REUSE_VERDICTS=0
export APPSECGATE_MASTER_URL="http://appsecgate-agent300-master:8000"
export APPSECGATE_MASTER_HOST_URL="http://127.0.0.1:8001"
export APPSECGATE_MASTER_API_KEYS="$(cat runtime/agent300-keys.json)"
export APPSECGATE_KNOWLEDGE_CUTOFF=""
export APPSECGATE_NUM_PARALLEL_MAX=4

run_cell() {
  local label="$1" internal="$2" sort="$3" mode_b="$4"
  echo "=== cell ${label}: internal=${internal} sort=${sort} mode_b=${mode_b} $(date +%H:%M:%S) ==="
  BENCH_LABEL="${label}" BENCH_PROJECT_ID_LABEL="${label}" \
    APPSECGATE_AGENT_INTERNAL_PARALLEL="${internal}" \
    APPSECGATE_AGENT_BATCH_SORT="${sort}" \
    APPSECGATE_MODE_B="${mode_b}" \
    BENCH_PARALLELISM=1 \
    BENCH_PROJECTS="atopile" \
    BENCH_OUTPUT="ablation-${label}.json" \
    python3 benchmark_parallel.py
}

# A2: sorting, internal=2 external=1 to keep cells sequential (external=2 would
# overlap only with a second project; atopile alone makes external moot).
run_cell asa-d 2 mode_major 0
run_cell asa-d2 2 none 0

# A1: read_project_file at operating point E (4x1)
run_cell arf-on 4 mode_major 1
run_cell arf-off 4 mode_major 0

echo "=== ablations done $(date +%H:%M:%S) ==="
