# Guided agent mode: analysis, implementation and validation

**Date:** 2026-11-05
**Status:** Release candidate frozen; corpus sourcing in progress
**Related:** ADR-0015 (§4, §10), ADR-0014, `docs/open-tasks.md`

## 1. Goal

Replace the top-10 triage experiment with a free agent that verdicts **all**
findings, then run the main 300-repository corpus (extensible to 1000).
The legacy paired baseline is not preserved. During validation the free
agent loop proved unviable on local models, so a guided mode was designed,
implemented and validated against the free mode and against DeepSeek-4.1.

## 2. ClickHouse log analysis (litellm.spend_logs)

### 2.1 Where time and tokens went in free mode

Run of 2026-11-04 (v4, batch=20, CodeWiki+zep in parallel, gemma-4-26B):
152 LLM calls, 64 min wall, 90.8 GPU-min, 2.25M prompt / 165k completion
tokens. Only **80 unique findings** received a verdict.

- **45% of calls (68/152) truncated at max_tokens=2048.** Responses were cut
  mid-sentence inside the verdict JSON (finish_reason misleadingly `stop`),
  so batches were lost and retried. Waste: ~1424 partial verdicts, 1.14M
  prompt tokens, 58 GPU-min.
- **~47% duplicate verdicts** in valid submits (153 instances over 80 IDs):
  the agent lost track of accepted findings after retries.
- **No prefix caching** (`cache_read_tokens ≈ 0`, ollama `/api/generate`).
  Prefill ≈ 430 tok/s, decode ≈ 30 tok/s; a 16k prompt costs 35–40 s before
  any output. Context pinned at the 16384 cap on most calls.
- **Two runs sharing one GPU**: 64 min wall vs 90.8 GPU-min — no speedup,
  higher timeout risk.
- v2/v3 (2026-11-02/03) had little truncation but 300–520 small round-trips
  per run and hit 30-min timeouts. CodeWiki v2: ~25k tokens per verdict.

Conclusion: the bottleneck was token-budget management and structured-output
reliability, not tool routing or scanner time (MCP calls are milliseconds,
scanners seconds).

### 2.2 Design consequence

A deterministic batch loop with bounded evidence freedom fixes the token
budget without model-specific tuning: batch size derives from
`llm_max_tokens`, not from a model name.

## 3. Implementation (mcp-server)

- `agent/guided.py` — guided loop: inventory paging, `get_fix_context_batch`
  prefetch, dependency-manifest prefetch (requirements*, go.mod,
  package-lock.json etc., up to 400 lines, ≤20k chars), one self-contained
  request per batch.
- **Bounded evidence loop**: within a batch the model may call
  `read_project_file` and master knowledge tools before its single
  `submit_verdicts` per finding (`_MAX_BATCH_ITERATIONS = 4`). Verdicts are
  never revised; the journal stays append-only.
- **Batch size** = `min(20, (llm_max_tokens // 2) // 120)` → 8 at 2048.
- **Retry logic**: truncated/invalid batch → split in half; partial ID
  omission → retry remaining (depth-limited); single invalid → explicit
  pending (`failed_findings`, `guided_incomplete`), never silent NEEDS_REVIEW.
- **Content-JSON fallback** for models without reliable tool calling.
- `agent/models.py` — `AgentConfig.agent_mode` (`free` default, `guided`),
  `guided_prompt_path`; `prompt_sha256` covers the guided prompt.
- `agent/cli.py` — `--agent-mode` / `APPSECGATE_AGENT_MODE`.
- `agent/runner.py` — mode selection; the scan always completes before the
  LLM starts and no scan tools exist for the model. Token-budget excess is
  an error only while findings are pending; a fully triaged run completes
  with a budget warning.
- Master integration unchanged: verdict journal → outbox → master
  `triage_verdicted` events; master read tools available in both modes.
- Experiments: `invoke-docker.sh` passes `APPSECGATE_AGENT_MODE`;
  `BENCH_MODELS` overridable in `make experiment-dev-run`;
  `prepare_agent_corpus.py` clones in parallel (8 workers) and calls
  `git ls-remote` only on the tarball fallback path.

## 4. Validation results

### 4.1 Free vs guided (gemma-4-26B)

| Run | Coverage | Time | Tokens | Notes |
|---|---|---|---|---|
| CodeWiki free v2 | 32/85 | 25.6 min | ~800k | token limit |
| CodeWiki guided g2 | 85/85 | 186 s | 119k | 0 retries |
| zep free v2/v3 | 17–23/256 | 13–30 min | — | repeat limit / timeout |
| zep guided g3b | 256/256 | 582 s | 487k | 0 retries |
| zep guided g5 | 256/256 | 650 s | 495k | 1 omission retry |

### 4.2 DeepSeek-4.1 (guided, same image)

CodeWiki 85/85 in 97 s, zep 256/256 in 299 s; 2 batch retries. One
well-reasoned FP (`shell=True` + `shlex.quote`). Mode is not model-specific.

### 4.3 Bugs found and fixed

1. **FP/NR from incomplete evidence** (g1): "package not listed in snippet"
   verdicts. Fixed by manifest prefetch + prompt rule: absence in a snippet
   is not evidence of absence. g2: all affected findings became TP with
   manifest line evidence.
2. **Token-budget hard failure after full triage** (g3): 256/256 verdicts
   accepted, run still errored at 502k > 500k. Fixed: budget excess fails
   only pending runs (ADR-0015 §10). Budget guidance: ~2k tokens/finding.
3. **Partial omission without retry** (g4): one finding omitted from a batch
   submit stayed failed. Fixed: remaining IDs are retried; g5 confirmed
   256/256 with a single retry.
4. **Makefile hardcoded BENCH_MODELS**: a DeepSeek run silently started as
   gemma; fixed to allow overrides.

### 4.4 Ollama validation

`FLASH_ATTENTION=1`, `KV_CACHE_TYPE=q8_0`, `PREFILL_CACHE=1`,
`KEEP_ALIVE=-1`, `LOAD_TIMEOUT=20m`. Verdict parity with the g2/g3b
references (g4/g5). **q8_0 accepted**; timing gain ~5% (small shared prefix
in guided). Prefix caching is a throughput option, not a correctness factor.

### 4.5 Tests

Mock smoke T-01/T-04/T-07 = true on guided. `make check` green:
535 mcp-server + 148 master (2 skipped) + 8 appsecgate-agent.

## 5. Frozen decisions

See `docs/open-tasks.md` → "Release candidate guided-agent (2026-11-05)"
and "Перед основным корпусом 300". Guided is the corpus mode; free remains
an option for stronger models. Remaining before the main corpus: sourcing
300, frozen run config, master knowledge + OSV snapshot, readiness check,
then 300 main runs and 10 repeats.

## 6. Housekeeping (2026-11-05)

- Docker images pruned by the operator; rebuild via `make docker-build`
  (and `make docker-master-build` for master) before the next runs.
- `experiments/tp-0001/runtime`: 39G → 3.4G by deleting per-run
  `trivy-cache` copies (reproducible scanner caches; the shared cache and
  the preflight cache dir were kept). Verdict journals and reports kept.
- Corpus cloning parallelized (8 workers, `CORPUS_CLONE_WORKERS`), shallow
  `--depth 1 --single-branch --no-tags`, `ls-remote` only on fallback.
