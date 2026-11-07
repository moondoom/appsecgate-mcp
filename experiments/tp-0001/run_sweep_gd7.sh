#!/usr/bin/env bash
# GD-7 full sweep (ADR-0019 Part 3). Sequential arms, reuse OFF, num_ctx 36864.
# Reuses acceptance raw data: B=accb(+accb2), D=accd, E-atopile=acce.
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
  local label="$1" internal="$2" external="$3" projects="$4"
  echo "=== arm ${label}: internal=${internal} external=${external} projects=${projects} $(date +%H:%M:%S) ==="
  BENCH_LABEL="${label}" BENCH_PROJECT_ID_LABEL="${label}" \
    APPSECGATE_AGENT_INTERNAL_PARALLEL="${internal}" \
    BENCH_PARALLELISM="${external}" \
    BENCH_PROJECTS="${projects}" \
    BENCH_OUTPUT="sweep-${label}.json" \
    python3 benchmark_parallel.py
}

STARTED=$(date +%s)

# Heavy set: A (1x1), C (1x4). B/D/E-atopile reused from acceptance.
run_arm swa 1 1 "atopile,costrict"
run_arm swc 1 4 "atopile,costrict"

# Sustained load at operating point E (4x1): costrict+zep+CodeWiki back-to-back (~45 min)
run_arm swe 4 1 "costrict,zep,CodeWiki"

# F (2x1) on atopile: internal pipeline without external overlap
run_arm swf 2 1 "atopile"

# D2 sort sub-arm: internal=2 external=2, batch_sort=none, atopile
APPSECGATE_AGENT_BATCH_SORT=none run_arm swd2 2 2 "atopile"

# Variant arm (owner-approved): per-mode batch sizes + adaptive max_tokens at E on atopile
APPSECGATE_MODE_BATCH_SIZES='{"cve":16,"secret":12,"secrets":12,"sast":6,"iac":10}' \
APPSECGATE_ADAPTIVE_MAX_TOKENS=1 \
  run_arm swv 4 1 "atopile"

# Small set: B and D on structlog/aitextgen (CodeWiki reused), C on all three
run_arm smb 1 2 "structlog,aitextgen"
run_arm smd 2 2 "structlog,aitextgen"
run_arm smc 1 4 "CodeWiki,structlog,aitextgen"

echo "=== sweep wall: $(( $(date +%s) - STARTED ))s ==="
