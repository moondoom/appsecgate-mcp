# ADR-0016: LLM throughput — prefill-bound; smaller contexts first, parallelism second

**Status:** Proposed (backend + production-log + proxy-path matrix
complete; guided-sched prototype pending)
**Date:** 2026-11-05
**Related:** ADR-0015 (autonomous triage, guided mode), ADR-0014 (multi-mode image)

## 1. Context

The guided agent (ADR-0015 §4) was frozen for the TP-0001 corpus with a fixed
configuration: one ollama runner at `num_ctx=32768`, batch size 8
(`min(20, (llm_max_tokens//2)//120)`), and **external parallelism 1–2**.
Here `llm_max_tokens` is the **completion-token budget per LLM response**
(2048 in the frozen config), NOT the context length: batch size derives
from the output budget at ~120 completion tokens per finding, so 8 at
2048. It is unrelated to the 32768-token input context.
External parallelism was low because two runs sharing one GPU were assumed
to contend. Development data
(free mode, gemma-4-26B) showed no wall-clock gain from two parallel runs and
higher timeout risk, so `parallelism: 1` was initially frozen for the corpus,
then raised to 2 after a resource review.

Two questions remained open and motivated this study:

1. What is the real throughput/latency surface of the LLM host under
   parallelism (p1–p16) and context sizes (4k–64k)?
2. Can the agent controller exploit *heterogeneous* finding costs — e.g.
   switch the runner to a small context when a queue of cheap findings
   (secrets, manifest CVEs) justifies the reload — instead of running every
   batch at the maximum context?

The 300-repository corpus run was descoped by the operator in favour of this
research; the validated 20-run stage-1 corpus (100% unique-finding coverage,
PostgreSQL master) remains the functional reference.

## 2. Test stand

- **LLM host (mgmt, 10.0.0.222):** single NVIDIA GPU, 16 GiB VRAM
  (17 175 674 880 bytes), 23.4 GiB host RAM, 8 CPU cores.
- **Model:** `hf.co/unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q3_K_M` (Q3_K_M,
  ~13 GiB weights), ollama runner `llamacpp`, `CONTEXT=32768`,
  `KEEP_ALIVE=-1`, `FLASH_ATTENTION=1`, `KV_CACHE_TYPE=q8_0`,
  `PREFILL_CACHE=1`, `LOAD_TIMEOUT=20m`.
- **Metrics:** Prometheus on the LLM host — `nvidia_smi_*` (util, power,
  memory) and `node_cpu_seconds_total` / `node_memory_*`; sampled per
  iteration window.
- **Tooling:** `experiments/tp-0001/llm_perf_matrix_ollama.py`, stdlib only.
  Raw data: `experiments/tp-0001/runtime/llm-perf-matrix{,-p3b,-p4,-phase2}.json`.

## 3. Methodology

Synthetic OpenAI-free benchmark against the **native ollama API**
(`POST /api/generate`, host port 3030), not through LiteLLM (see §7).

- Per cell: fixed prompt size target (4k/8k/16k/32k/64k tokens of repeated
  filler + summarisation instruction), `num_predict=512`, `temperature=0`,
  `stream=false`.
- Parallelism p ∈ {1,2,3,4} (phase 1) and {4,8,16} (phase 2): p identical
  requests fired concurrently per iteration, **5 iterations per cell**.
- Every request carries a unique salt suffix to defeat prompt/KV-prefix
  caching of identical inputs.
- Recorded per request: ollama-reported `prompt_eval_count`,
  `prompt_eval_duration`, `eval_count`, `eval_duration`, `load_duration`,
  wall time; per iteration: GPU util avg/max, power, VRAM, CPU
  user/system/iowait, host RAM.
- Phase 1 keeps `num_ctx=32768` for prompts ≤32k (the already-loaded runner);
  only 64k crosses into a new runner. Phase 2 uses `--exact-ctx` (runner
  reloaded to the exact small context) to measure lane-switching economics.

## 4. Results — phase 1 (shared 32k runner, 64k cells on a 64k runner)

All 20 cells, 5 iterations each, **zero errors**. `wall` = mean iteration
wall seconds, `dec_agg` = aggregate decode tokens/s over p requests,
`pre` = mean per-request prefill tokens/s.

| cell | wall s | pre t/s | dec_agg t/s | GPU avg | VRAM GiB | CPU user |
|---|---|---|---|---|---|---|
| p1/ctx4096 | 6.6 | 23 236 | 65.9 | 55% | 14.0 | 24% |
| p1/ctx8192 | 6.6 | 52 812 | 63.8 | 86% | 14.0 | 36% |
| p1/ctx16384 | 8.8 | 93 229 | 57.0 | 80% | 14.0 | 40% |
| p1/ctx32768 | 12.2 | 203 491 | 47.5 | 86% | 14.0 | 44% |
| p1/ctx65536 | 21.4 | 310 725 | 36.6 | 97% | 14.5 | 50% |
| p2/ctx4096 | 12.6 | 26 898 | 132.7 | 86% | 14.1 | 41% |
| p2/ctx8192 | 12.9 | 61 208 | 127.3 | 84% | 14.0 | 43% |
| p2/ctx16384 | 16.7 | 98 541 | 114.5 | 71% | 14.0 | 47% |
| p2/ctx32768 | 20.3 | 239 387 | 96.1 | 79% | 14.0 | 49% |
| p2/ctx65536 | 34.4 | 399 912 | 73.4 | 88% | 14.5 | 52% |
| p3/ctx4096 | 18.1 | 27 358 | 198.5 | 87% | 14.1 | 46% |
| p3/ctx8192 | 18.7 | 62 738 | 189.9 | 83% | 14.0 | 46% |
| p3/ctx16384 | 22.9 | 120 919 | 170.1 | 83% | 14.0 | 50% |
| p3/ctx32768 | 28.5 | 257 334 | 144.7 | 84% | 14.0 | 47% |
| p3/ctx65536 | 46.8 | 434 206 | 110.4 | 93% | 14.5 | 52% |
| p4/ctx4096 | 23.4 | 28 286 | 267.0 | 89% | 14.1 | 49% |
| p4/ctx8192 | 25.1 | 64 645 | 255.6 | 97% | 14.0 | 49% |
| p4/ctx16384 | 33.0 | 118 212 | 229.5 | 89% | 14.0 | 52% |
| p4/ctx32768 | 39.5 | 244 465 | 191.7 | 90% | 14.0 | 52% |
| p4/ctx65536 | 58.7 | 436 045 | 146.5 | 86% | 14.5 | 53% |

Observations:

- Aggregate decode scales **linearly** with p at every context size;
  per-request decode is essentially constant (e.g. ~66 t/s at 4k for any p).
- 64k cells worked at every p: runner reload succeeded, no OOM, VRAM grew
  only ~0.5 GiB. Decode per request drops from ~66 (4k) to ~37 (64k).
- VRAM is flat in p: the runner pre-allocates its slots once.
- Host CPU grows moderately (24%→53%) and does not limit.

## 5. Results — phase 2 (exact small runners, high parallelism)

`--exact-ctx`, 5 iterations per cell, zero errors. `load_ms` ≈ 4 300 ms on
the first request of each cell = one runner reload between contexts.

| cell | wall s | dec_agg t/s | dec/req t/s | pre/req t/s | GPU avg | VRAM GiB | load_ms |
|---|---|---|---|---|---|---|---|
| p4/ctx4096 | 23.9 | 264.8 | 66.2 | 27 746 | 83% | 14.5 | 4 330 |
| p4/ctx8192 | 27.2 | 253.8 | 63.5 | 62 439 | 92% | 13.7 | 4 548 |
| p4/ctx16384 | 30.6 | 227.5 | 56.9 | 121 541 | 76% | 13.8 | 4 282 |
| p8/ctx4096 | 46.7 | 533.4 | 66.7 | 28 896 | 96% | 13.8 | 4 345 |
| p8/ctx8192 | 51.9 | 510.4 | 63.8 | 65 313 | 87% | 13.7 | 4 314 |
| p8/ctx16384 | 61.8 | 454.8 | 56.9 | 124 644 | 85% | 13.8 | 4 292 |
| p16/ctx4096 | 91.5 | **1 065.7** | **66.6** | 29 048 | 83% | 13.8 | 4 288 |
| p16/ctx8192 | 105.3 | 1 021.5 | 63.8 | 66 029 | 94% | 13.7 | 4 386 |
| p16/ctx16384 | 116.8 | 919.2 | 57.4 | 129 238 | 92% | 13.8 | 4 176 |

Observations:

- **Linear scaling holds to p16 with zero errors**: aggregate decode grows
  from 66 t/s (p1/4k) to 1 066 t/s (p16/4k); per-request decode is flat.
  No NUM_PARALLEL ceiling observed at 16.
- Small runners do **not** save meaningful VRAM (~13.8 vs ~14.0 GiB):
  weights dominate; KV per slot is cheap at 4–16k. Memory is not the
  parallelism constraint anywhere in the measured range.
- The value of a small context is decode speed: 66.6 t/s (4k) → 57 (16k)
  → ~47 (32k) → ~37 (64k). Short context ≈ +40% decode vs 32k.
- One runner reload costs ≈ 4.3 s.
- Power draw stays at 103–112 W avg (peaks ≤ 123 W) across p4–p16, well
  below the GPU power cap; no thermal pressure in short runs. Sustained
  multi-minute p16 behaviour is unverified (see §10).
- Not measured in this phase: p8/32k, p8/64k, p16/32k/64k. Any statement
  about those cells is extrapolation until the proxy-path matrix
  (§7, includes p8/p16 at 32k/64k) provides data.

## 6. Ollama execution model (as observed)

1. One runner serves one model at one `num_ctx`; concurrent requests are
   continuous-batched inside it.
2. A request whose `num_ctx` differs from the loaded runner triggers a
   **reload** (~4.3 s measured at 16k; includes model load). Distinct
   contexts are therefore *sequential lanes*, not parallel slots, on this
   16 GiB host (a second 13 GiB runner cannot coexist).
3. A 64k runner fits and serves p4 without OOM (KV_CACHE_TYPE=q8_0 helps).
4. VRAM is insensitive to p; decode throughput per request is insensitive
   to p in p1–p16. Decode is the scarce resource and is shared fairly.

## 7. Pitfall: benchmarking through LiteLLM requires explicit `num_ctx`

**Invariant: the agent (and any prototype under test) talks to the LLM only
through the LiteLLM proxy** (`:4000/v1`). Direct ollama access is outside
the test conditions; the native-API matrix in §4–§5 is a *backend ceiling*
measurement, not the production path.

An identical matrix initially ran through the proxy **without `num_ctx`**
and produced falsified data: large prompts were silently truncated to
`prompt_tokens=2051` regardless of their true size. Root cause established
by direct A/B requests: without an explicit `num_ctx`, the ollama path
truncates the prompt to the runner's default budget; passing
`num_ctx=32768` in the request body restores the full prompt
(verified: 16 037 prompt tokens vs 2 051 without it). The sub-second
responses for repeated prompts were the ollama prefix cache
(`PREFILL_CACHE=1`) on the truncated identical prefix, not a proxy cache.

The agent itself is unaffected: its requests carry
`APPSECGATE_LLM_NUM_CTX=32768` explicitly, and ClickHouse
`litellm.spend_logs` confirms full prompts of 10k–30k tokens.

The proxy config (`~/appsecgate-lab/litellm/config.yaml` on mgmt) also
enables a `hide_secrets` pre-call guardrail and has no `model_list` entry
for the gemma model (pass-through provider routing); neither affects the
measurements once `num_ctx` is set.

Rules for any future benchmark on the test stand:
1. go through LiteLLM (test invariant);
2. always pass `num_ctx` explicitly;
3. salt prompts and verify reported `prompt_tokens` against the target.

A proxy-path re-run of the matrix (p1/2/4/8/16 × 4k–64k, streaming
TTFT/decode, salted prompts, explicit `num_ctx`) is recorded in
`runtime/llm-perf-matrix-proxy.json`; §4–§5 remain the backend reference.

**Proxy-path results (production path): all 25 cells, zero errors.**
`wall` = mean iteration seconds, `dec_agg` = aggregate decode tokens/s,
`dec/req` = per-request decode tokens/s.

| cell | wall s | dec_agg t/s | dec/req t/s | VRAM GiB | native dec_agg (§4–§5) |
|---|---|---|---|---|---|
| p1/4k | 7.7 | 65.2 | 65.2 | 14.0 | 65.9 |
| p1/8k | 8.9 | 63.3 | 63.3 | 13.7 | 63.8 |
| p1/16k | 8.9 | 56.5 | 56.5 | 13.8 | 57.0 |
| p1/32k | 13.7 | 46.7 | 46.7 | 14.0 | 47.5 |
| p1/64k | 21.7 | 35.4 | 35.4 | 14.5 | 36.6 |
| p2/4k | 13.5 | 130.0 | 65.0 | 14.5 | 132.7 |
| p2/8k | 15.8 | 125.6 | 62.8 | 13.7 | 127.3 |
| p2/16k | 18.4 | 112.6 | 56.3 | 13.8 | 114.5 |
| p2/32k | 21.8 | 93.3 | 46.6 | 14.0 | 96.1 |
| p2/64k | 33.8 | 70.9 | 35.5 | 14.5 | 73.4 |
| p4/4k | 25.8 | 263.4 | 65.8 | 14.5 | 267.0 |
| p4/8k | 30.6 | 248.4 | 62.1 | 13.7 | 255.6 |
| p4/16k | 34.0 | 225.6 | 56.4 | 13.8 | 229.5 |
| p4/32k | 42.0 | 190.2 | 47.5 | 14.0 | 191.7 |
| p4/64k | 60.5 | 143.9 | 36.0 | 14.5 | 146.5 |
| p8/4k | 49.0 | 527.5 | 65.9 | 14.5 | 533.4 |
| p8/8k | 57.9 | 506.4 | 63.3 | 13.7 | 510.4 |
| p8/16k | 63.6 | 454.8 | 56.8 | 13.8 | 454.8 |
| p8/32k | 80.6 | 379.9 | 47.5 | 14.0 | — |
| p8/64k | 113.1 | 288.2 | 36.0 | 14.5 | — |
| p16/4k | 102.4 | 1 056.6 | 66.0 | 14.5 | 1 065.7 |
| p16/8k | 115.4 | 1 012.6 | 63.3 | 13.7 | 1 021.5 |
| p16/16k | 126.7 | 905.1 | 56.6 | 13.8 | 919.2 |
| p16/32k | 150.1 | 754.5 | 47.2 | 14.0 | — |
| p16/64k | 216.3 | 567.7 | 35.5 | 14.5 | — |

The proxy matches the native backend within ~1–2% on shared cells and
extends the linear scaling result to p8/p16 at 32k and 64k, including
p16/64k (567.7 t/s aggregate, no OOM). The production path therefore does
not cap the measured parallelism: the §4–§5 numbers are valid for design.

### 7.B Unique-prompt matrix (prefix cache defeated): the real bottleneck

The matrices above carry a measurement artefact: the salt sat at the END
of the prompt, so ~99% of every prompt was a shared prefix and ollama's
`PREFILL_CACHE=1` made prefill nearly free. Real guided batches are
unique content. Re-run with the salt FIRST (full cache defeat), 16k
prompts, 512-token completions, 3 iterations per cell
(`runtime/llm-perf-noprefixcache.json`):

| cell | wall s | TTFT s | agg decode t/s | sequential-equivalent s | speedup |
|---|---|---|---|---|---|
| p1/16k | 12.7 | 5.2 | 54.6 | 12.7 | 1.00× |
| p2/16k | 19.4 | 7.3 | 112.4 | 25.4 | 1.31× |
| p4/16k | 40.0 | 18.8 | 221.8 | 50.8 | 1.27× |
| p8/16k | 92.2 | 44.1 | 446.8 | 101.6 | 1.10× |

Decode is still linear — but it does not matter: **prefill is
compute-bound (~3 000 t/s aggregate, flat in p)** and dominates wall
time. TTFT grows 5.2 → 44.1 s as prefills queue. Real speedup from
parallelism on unique prompts is **1.1–1.3×**, not ×8. A staggered-arrival
variant (random 0–10 s offsets, p2/4/8 at 16k,
`runtime/llm-perf-stagger.json`) showed no additional degradation
(agg decode 448 vs 455 simultaneous): arrival timing is irrelevant;
unique prefill is the whole story.

Open arithmetic gap: the simple model (8 × 5.2 s prefill + 9.2 s decode
≈ 52 s) under-predicts the p8 wall (92.2 s) by ~40 s. Candidate
mechanisms: prefill throughput degrades under concurrency, prefill and
decode do not overlap on this GPU, or scheduler overhead. Unverified;
all three imply the p2–4 target is conservative and must be confirmed
on real runs (§9.4). A cheap follow-up is per-request
`prompt_eval_duration` at p8 (native API) to separate prefill
degradation from prefill/decode serialisation.

This also explains the production residuals (§8.A): at 15k tokens a real
batch pays ~5 s prefill + ~12 s decode ≈ 17 s (proxy overhead ≈ 0), and
p2 adds prefill queueing, matching the dev report "two runs, no speedup"
and the free-mode prefill ~430 tok/s observations.

**Consequence (priority reversal, final): the lever is prefill
reduction, not parallelism.** Smaller prompts (8k/16k lanes, compact
evidence) cut the bottleneck directly; internal batch parallelism yields
only ~10–30% on this workload.

### 7.C Memory (GPU VRAM and host RAM)

Measured per iteration window on every cell; values are maxima over the
cell (GiB). Host RAM total: 23.4 GiB; GPU total: 16.0 GiB.

| cell | VRAM GiB | host RAM GiB |
|---|---|---|
| p1/4k | 13.99 | 4.64 |
| p1/16k | 13.77 | 4.78 |
| p1/32k | 13.99 | 4.21 |
| p1/64k | 14.48 | 4.65 |
| p4/4k | 14.48 | 4.89 |
| p4/16k | 13.77 | 5.01 |
| p4/32k | 14.00 | 4.64 |
| p4/64k | 14.49 | 4.93 |
| p16/4k | 14.49 | 5.20 |
| p16/8k | 13.68 | 5.17 |
| p16/16k | 13.77 | 5.13 |
| p16/32k | 14.00 | 4.77 |
| p16/64k | 14.49 | 5.29 |
| unique-prompt p1/16k | 13.77 | 6.03 |
| unique-prompt p2/16k | 13.77 | 7.44 |
| unique-prompt p4/16k | 13.77 | 11.05 |
| unique-prompt p8/16k | 13.77 | 12.06 |

Facts:

- **VRAM is flat in p at every context**: 13.7–14.5 GiB of 16 GiB across
  the entire matrix, including p16/64k. Weights (~13 GiB) dominate; KV
  (`q8_0`) adds ≤0.5 GiB for 64k runners. Parallelism and small-context
  lanes change nothing material — memory is NOT the constraint anywhere
  in the measured range, and a second model runner cannot fit anyway.
- **Host RAM is flat (~4.2–5.3 GiB) on cache-assisted prompts**, but
  grows on unique-prompt high-p runs: 6.0 → 12.1 GiB at p8/16k
  (proxy/ollama request batching buffers for 100+ KB unique prompts).
  At p16 unique this projects to ~20+ GiB of 23.4 GiB total — host RAM,
  not VRAM, is the first ceiling to hit if high-p is ever attempted with
  unique large prompts. Not measured at p16 unique; projection from the
  p8 measurement. Another argument for the modest p2–4 target
  (§8.3) and for smaller prompts.
- No swap pressure or OOM was observed in any cell (zero errors).

## 8. Decision (proposed): guided-sched — lane-aware scheduling in the agent controller

### 8.A Production distribution (litellm.spend_logs, 598 guided calls, 2026-11-05)

| metric (batch of 8) | p10 | p50 | p90 | p99 |
|---|---|---|---|---|
| prompt_tokens | 8 055 | 15 304 | 22 990 | 29 721 |
| completion_tokens | 427 | 650 | 766 | 1 145 |
| call duration, s | — | 18 | 37 | 48 |

- Per-finding prompt cost: ~1.2–2k tokens (CVE batches cheaper:
  median 8 164/batch; evidence-tool batches: median 16 285/batch).
- `evidence_reads` ≈ 0 in stage-1 reports: the model almost never reads
  project files, so the 32k evidence lane is rarely needed.
- `cache_read_tokens = 0` on the proxy path.
- **Overhead decomposition — resolved: there is NO proxy/guardrail
  overhead.** Residual = duration − completion/56 t/s − prompt/3 000 t/s
  (prefill rate from §7.B, not the cache-inflated 93k t/s):

  | phase | calls | duration p50 | residual p50 |
  |---|---|---|---|
  | dev, sequential (p1) | 518 | 16.2 s | **−0.4 s** |
  | stage-1, two agents (p2) | 232 | 29.6 s | 13.9 s |

  At p1 the prefill+decode model fully explains call duration (residual
  ≈ 0): proxy and the `hide_secrets` guardrail are effectively free for
  this workload. Nothing can be gained by optimising the proxy (or any
  alternative proxy implementation). The p2 residual (+13.9 s) is
  prefill queueing, not proxy cost — consistent with §7.B.

Consequences for the design:

1. **Lanes apply to batches, not findings.** A batch of 8 costs
   8 × ~1.9k + template ≈ 15k tokens minimum, so a 4k lane is
   unrealistic at batch size 8. Realistic lanes: 8k/16k/32k, with batch
   size derived from the per-finding cost estimate and the lane budget.
2. **Lane gains are substantial once prefill is priced in (§7.B).**
   Decode-only accounting (~20% at 16k vs 32k) understates the win:
   a 15k batch pays ~5 s prefill at ~3 000 t/s, so an 8k lane cuts the
   dominant cost roughly in half on covered batches, plus ~20% decode.
   Expected gains must be computed as prefill + decode, not decode only.
3. **Internal batch parallelism is a minor lever (measured 1.1–1.3×,
   §7.B), not the dominant one.** The primary reserve is **prefill
   reduction**: smaller prompts (8k/16k lanes), compact evidence
   (trimmed fix-context, manifest excerpts), and prefix reuse of the
   shared template. Parallelism is a small additional win and should
   stay modest (p2–4) to limit prefill queueing. This replaces the
   earlier "internal parallelism first" conclusion; the prefill ceiling
   is the primary finding of this ADR.
4. Completion distribution (p50 650, p99 1 145) confirms the §8.2
   sensitivity table (512-token row is the conservative case).
5. Since `evidence_reads ≈ 0`, **the 32k lane is a safety net, not a
   routine lane**: the effective lane decision for most batches is
   8k vs 16k, and 32k is reserved for the rare oversized batch.

Keep the frozen guided mode unchanged for reference runs. Add an opt-in
`agent_mode=guided-sched` behind a flag with:

0. **Single-tenant constraint and the adoption bar (explicit).**
   guided-sched switches the runner's `num_ctx` between lanes, and one
   runner serves one `num_ctx` (§6). Its in-flight parallelism is
   *inside one agent process*, not a sum over processes. Multi-process
   lane switching requires a global lane coordinator (out of scope).
   **Adoption must be decided by direct comparison, not assumed:**
   frozen guided at external p2 processes a 16k batch at 19.4 s wall
   with two in flight → **9.7 s effective per batch**. guided-sched at
   external p1 on an 8k lane costs ~2.7 s prefill + ~10.2 s decode
   (650 tokens at 63.8 t/s) ≈ **12.9 s per batch — it LOSES to frozen
   p2** unless prefill cuts are larger, batches get cheaper, or
   lane-switched p1+lane runs at p2 internally without reload
   thrashing. Therefore: (a) the single-tenant constraint is a
   potential deal-breaker, not a footnote; (b) §9.4 must include the
   explicit gate "guided-sched effective seconds/batch < frozen p2
   effective seconds/batch"; (c) if the gate fails, the fallback is
   frozen guided at p2, and lane ideas survive only as prefill
   reduction inside the existing p2 setup (same `num_ctx`, smaller
   prompts — no lane switching at all).
1. **Deterministic finding cost classifier** (no LLM):
   - secret findings (gitleaks/trufflehog, short snippet) → 4k lane;
   - dependency/CVE findings with manifest prefetch → 4–8k lane;
   - SAST findings from a snippet → 8–16k lane;
   - findings requiring `read_project_file` evidence → 32k lane.
   Signals: scanner, rule id, snippet size, manifest presence, file type.
   **Escalation policy:** the classifier can underestimate (long secret
   snippet, unusual manifest, huge evidence file). If a finding's actual
   context exceeds its lane, the finding is **escalated to the next larger
   lane and the escalation is counted in metrics** — never silently
   truncated. Truncation of evidence is a correctness risk (FP/NEEDS_REVIEW
   drift), not a performance knob.
   **Smaller-is-better caveat:** a larger lane is not a quality upgrade.
   Published evidence (PREFENSE, IEEE CAI 2026) shows extra context can
   degrade model judgement. A finding that can be judged correctly in an
   8k lane SHOULD stay there; the 32k lane exists only for evidence that
   genuinely does not fit smaller lanes. Per-lane verdict quality is
   checked in §9.3.
   **Post-hoc classifier validation:** after every guided-sched run, the
   actual prompt lengths (from logs) are compared against the predicted
   lane. If misclassification (actual context needing a larger lane)
   exceeds **10%** of findings, the classifier must be revised before the
   ADR can be accepted — prompt-length heterogeneity within one finding
   type is extreme in production traces (LBSL: mean ~6k, P99 16k–22k), so
   type-based prediction alone is not trustworthy by default.
2. **Lane scheduling**: group pending findings by estimated context lane;
   a runner reload is justified when the lane's expected decode saving
   exceeds the reload cost. Measured economics (§5): decode 66 t/s (4k)
   vs 47 t/s (32k) saves ~0.00614 s per completion token; reload ≈ 4.3 s.

   | completion tokens | saving/finding vs 32k | break-even lane size |
   |---|---|---|
   | 512 | ~3.1 s | 2 findings |
   | 1024 | ~6.3 s | 1 finding |
   | 2048 | ~12.6 s | 1 finding |

   The 512-token row is the conservative case (a plain verdict); guided
   batches with tool calls/evidence reach 1500–3000 tokens, so real
   break-even is even earlier. **Prefill saving (§7.B) is the dominant
   term**: at ~3 000 t/s, moving a 15k batch to an 8k lane saves ~2.3 s
   prefill per batch in addition to decode — usually exceeding the
   decode-only savings in the table above.
3. **Modest in-flight parallelism**: the unique-prompt matrix (§7.B)
   caps real gains at 1.1–1.3× (prefill queues), so target **p2–4**, not
   p8–16. Decode scales linearly to p16 on the proxy path (§7: p16/32k =
   754.5 t/s; p16/64k = 567.7 t/s, zero errors), but wall time on unique
   prompts is prefill-dominated, and higher p only lengthens TTFT.
   The earlier "×16 headroom" framing is superseded by §7.B.
   **Architecture-specificity:** the p16 linearity was measured on a MoE
   model with ~4B active parameters (gemma-4-26B-A4B). Published
   benchmarks (club-3090, Harmonic Stack, 2026) show dense models and
   larger-active-parameter MoE models saturate far earlier (e.g. dense
   27B peaks at N=2). Parallelism is therefore a **profiled per-model
   setting, never hardcoded**; a new model requires re-running the matrix.
4. **Honest degradation**: the synthetic matrix is a best case — uniform
   prompts, simultaneous starts, equal 512-token completions. Real guided
   batches stagger arrivals (prefill of new requests interleaves with
   decode of running ones), completions vary in length, and slots
   underfill. Expected gains must therefore be validated against the
   frozen guided baseline on the real completion-length distribution of
   the heavy repositories (atopile 167 findings, PilotDeck 121,
   costrict 115), not read off the synthetic tables.
   **Tail latency is an acceptance criterion, not an afterthought:**
   prediction-based schedulers are fragile under distribution shift and
   arrival bursts, and tail latency can regress even with perfect length
   prediction (Beyond Prediction / Tail-Aware Scheduling, ICML 2026;
   RPSC, ICPP 2026). guided-sched must not degrade P90/P99 triage latency
   versus frozen guided; on tail degradation the fallback is frozen
   guided, not a tuned variant.

5. **Open questions (unmeasured):**
   - *Batch size as a prefill/interleaving lever.* A batch of 4 costs
     ~7.5k prefill vs 15k for 8; with serialised prefill, smaller batches
     may interleave better with decode and smooth TTFT. Not measured.
   - *Shared-template prefix reuse.* The guided template (~2k of the 15k
     prompt, ~13% prefill) is cacheable across batches of one run;
     ordering batches to exploit this may exceed the entire p2–4 gain.
     Not quantified.

Non-goals: changing verdict semantics, evidence rules, journal format, or
the frozen corpus configuration; serving multiple model runners
concurrently on this 16 GiB host; multi-process lane coordination (§8.0).

## 9. Verification plan

1. Prototype `guided-sched` behind `APPSECGATE_AGENT_MODE`; all runs go
   through the LiteLLM proxy with explicit `num_ctx` (invariant, §7);
   external parallelism 1 (single-tenant, §8.0).
2. Parity: CodeWiki/zep verdicts must match the g2/g3b/g5 references by
   finding_id; coverage 85/85 and 256/256, zero failed_findings.
3. **Cross-lane verdict consistency and per-lane quality:** run the same
   corpus through frozen guided (32k) and guided-sched, then compare
   verdicts **pairwise by finding_id** between the two runs. Systematic
   drift means the lane affects semantics and the design fails, even if
   reference parity holds. Additionally compare verdict distribution
   **per lane**: if the 32k lane yields more FP or NEEDS_REVIEW than the
   8k lane on comparable findings, automatic escalation to 32k is
   rejected (PREFENSE: more context can hurt).
4. Benchmark wall time, total tokens, batch_retries, lane-escalation
   counts and timeouts on the heavy stage-1 repositories against frozen
   guided at p2, using the real completion-length distribution.
   Report **P90/P99 latency per finding** alongside means (§8.4).
   **Adoption gate (§8.0):** guided-sched effective seconds/batch must
   beat frozen p2 effective seconds/batch (9.7 s at 16k); otherwise
   fall back to prefill reduction inside frozen p2, no lane switching.
   **Classifier post-hoc check:** predicted lane vs actual prompt length
   from logs; misclassification >10% blocks acceptance (§8.1).
   **Template-cache hit rate:** quantify the shared-template prefix
   reuse (§8.5) from the run logs — it may exceed the entire p2–4 gain.
5. **Sustained-load check:** at least one ≥30-minute **p4** run (the
   target range from §8.3) on the real completion-length distribution
   with power and thermal telemetry, plus one p16 sanity run to exclude
   a thermal cliff. Record errors plus **P99 TTFT and P99 inter-token
   latency**: rising P99 under sustained load invalidates the short-run
   results (5-iteration cells prove neither thermal nor tail stability).
6. `make check` green before any merge decision.

## 10. Risks

- **Single-tenant vs corpus parallelism — possible deal-breaker.**
  The §8.0 arithmetic shows guided-sched p1+lane can LOSE to frozen
  p2 (12.9 vs 9.7 effective s/batch). Adoption only after the explicit
  §9.4 gate passes; fallback is prefill reduction inside frozen p2
  without lane switching.
- **Synthetic-vs-real gap.** ×16 aggregate decode is an upper bound from
  uniform simultaneous requests; staggered arrivals and heterogeneous
  completions will reduce it. No production throughput claim is made
  before §9.4.
- **Tail regression.** Lane scheduling optimised for mean throughput can
  worsen P99 under arrival bursts or distribution shift; §8.4 makes tail
  latency a pass/fail criterion with frozen-guided fallback.
- **Architecture-specific scaling.** The linear p16 result belongs to a
  ~4B-active-parameter MoE; other model families require their own
  profiling (§8.3).
- **Parallelism ceiling — closed; real-workload gain — open.**
  The proxy matrix (§7) measured every cell through p16/64k with zero
  errors, so the ceiling question is settled. The GAIN on unique-prompt
  production workloads is 1.1–1.3× (§7.B), not the synthetic ceiling;
  §9.4 confirms the actual number.
- **Classifier misclassification.** Type-based lanes ignore extreme
  within-type length variance (LBSL traces); mitigated by mandatory
  escalation (§8.1), the >10% post-hoc gate (§9.4) and §9.3 verdict
  comparison.
- **Verdict drift across lanes.** The same finding may be judged
  differently at 4k vs 32k context; more context can also actively hurt
  (PREFENSE). §9.3 is the dedicated check.
- **Sustained thermals and tails.** All cells are 5 short iterations;
  long p16 runs may throttle or develop P99 degradation (§9.5).
- **Status guidance.** Status stays `Proposed` until §9.2–§9.5 pass;
  moving to `Accepted` on synthetic data alone would repeat the
  ADR-0015 assumption error this ADR is correcting.

## 11. Prototype results (2026-11-05, guided-sched v3)

Implementation: `agent_mode=guided-sched` (`agent/guided_sched.py`),
per-batch lane from conservative prompt estimate (`chars//3 + 4000`),
lane-affinity (payloads prebuilt, chunks sorted by lane, lanes run
sequentially, parallelism only within a lane), truncation escalates to a
larger lane, internal `sched_parallel=2`. Plus `reuse_verdicts`
(default ON, all modes): prior master verdicts are reused by finding
fingerprint, shifted lines re-triage; usage `reused_verdicts`.
`make check` green (535+148+8).

| run | frozen guided | guided-sched v3 | tokens |
|---|---|---|---|
| CodeWiki | 85/85, 186 s | 85/85, **180 s** | 121k vs 119k |
| atopile | 167/167, 670 s (external p2) | 167/167, **458 s** | 411k vs 405k |

- **Adoption gate (§8.0) PASSES on atopile**: 19.9 effective s/batch vs
  frozen p2 30.5 s/batch → **1.46× wall-time speedup**, 0 retries,
  0 escalations, 0 failed, 0 lane underestimates.
- atopile batches all landed in the 32k lane (conservative estimate):
  the measured win came from **internal parallelism**, not lane
  switching. CodeWiki batches all fit 16k (one reload): time parity.
- Failed intermediate iterations (documented for the record): v1
  (`lane_*` counter bug), v2 (per-batch ad-hoc lanes → reload thrash +
  underestimated prompts → 71 calls / 754k prompt tokens / token-budget
  failure on atopile). Lane-affinity and the conservative estimator
  eliminated both, confirming the diagnosis.
- Reuse was not exercised in these dev runs (no master); it requires a
  separate check on the master-enabled contour.

**Sweep (2026-11-06, guided-sched v3, internal p2, external p1):**

| repo | frozen guided | sched v3 | speedup | verdict parity |
|---|---|---|---|---|
| zep | 582–650 s | 641.9 s | ~1× | 255/256 |
| PilotDeck | 732 s | 530.2 s | 1.38× | 121/121 |
| costrict | 584 s | 363.9 s | 1.60× | 106/106 |
| vibetunnel | 373 s | 217.1 s | 1.72× | 77/86 (9 drift) |

Full coverage everywhere, 0 failed_findings. PilotDeck/costrict
inventories grew (scanner DB update) with identical verdicts on all
common finding_ids. vibetunnel shows 9/86 verdict drift (TP→FP on
SSRF/secret heuristics) — flagged for the per-lane quality review;
not yet attributed to lanes vs model variance.

**Reuse validation (2026-11-06, master PostgreSQL):** AzuraCast rerun
with prior stage-1 verdicts on master: `reused_verdicts=14/14`, **zero
LLM calls**, 17 s (scan only) vs 82 s. Fingerprint-matched reuse works;
shifted lines fall through to full triage by construction.

Remaining before any status change: zep parity, heavy-repo sweep
(PilotDeck, costrict, vibetunnel), P90/P99 and sustained-load check
(§9.5), reuse validation, then corpus decision.

## 12. Update 2026-11-06: lane num_ctx switching removed (§8 fallback enacted)

Live `agent300fix1` run exposed the thrash the ADR warned about: **14
runner reloads in 90 minutes** because `guided_sched` passed per-lane
`num_ctx` (8k/16k/32k) while `_triage_chunk` sent it per request; each
switch rebuilds the runner and wipes the prefix cache. Fix enacts the
§8 fallback: lanes now size prompts and feed `lane_*` /
`lane_underestimated` stats only; every request carries constant
`config.llm_num_ctx` (36864 = 32k lane + output reserve, avoids the
silent truncation of >32k prompts observed on a 32768 slot). Server
side: `OLLAMA_NUM_PARALLEL=4` explicit (auto silently gave 1 slot from
the trained 262144 context — all client parallelism serialized), slots
4×36864, KV q4_0. Measured on RTX 4060 Ti 16 GB: aggregate decode
~64 → ~78 t/s at par4 (bandwidth-saturated); the real win is pipeline
overlap and no head-of-line blocking, not raw throughput. The "2–4%
CPU" in `ollama ps` is the idle vision encoder (mmproj ~1.1 GB)
CPU-mapped, not compute layers — no perf impact for text-only runs.

## 14. Planned: guided tuning sweep and timeout calibration (2026-11-07)

`experiments/tp-0001/scenario_add.md` supersedes the proposed lane-switching
design **only after its acceptance gates pass**; §8 is not retroactively
marked accepted or superseded before that experiment. The target design is
one `guided` mode with constant `num_ctx=36864`, `internal_parallel`,
`batch_sort=mode_major`, and `internal × external ≤ 4` enforced by the
launcher. Lanes remain telemetry only.

Timeout rule for that experiment: **600 s provisional**, not 90 s. The §8.A
p99=48 s distribution was measured at different concurrency and cannot cap
four-slot traffic; at ~20 t/s per stream a legitimate 2048-token response
takes ~102 s before prefill. Arm D at 600 s supplies a fresh distribution;
the production timeout is then `p99 × 1.5` rounded to 30 s, after checking
that slower calls are genuine failures. Acceptance separately gates
`context_overflow ≤5%` and `timeout ≤1%`; only the former answers whether
32k is sufficient. Wall-speed gates use `speedup = wall(baseline arm) /
wall(candidate arm)`, and verdict parity compares arms with identical batch
composition and prompt hashes. Acceptance includes current-production E
(4×1) on atopile; D (2×2) is adopted only if it does not regress against E
on wall/P99, not merely because it beats B. Cache-hit analysis requires
explicit cache counters, never `(prompt_tokens − prompt_eval_count) /
prompt_tokens`.

## 15. References (as cited in review)

- Beyond Prediction: Tail-Aware Scheduling (ICML 2026) — prediction-based
  schedulers are fragile to distribution shift; P99 tail degrades even
  with perfect length prediction; prediction-free policies cut P99 TTLT
  by 35–50% vs oracle SRPT.
- RPSC (ICPP 2026) — scheduling tolerant to length-prediction error.
- LBSL (Load-Balanced Stochastic Length) — production prompt-length
  traces: mean ~6k, P99 16k–22k within one request type.
- club-3090 (2026-07) — MoE 35B-A3B scales aggregate throughput to N=16;
  dense 27B peaks at N=2 and degrades by N=8.
- Harmonic Stack (2026) — different architectures prefer different
  parallelism sweet spots.
- Ollama vs vLLM (Vercel, 2026-08) — ollama defaults
  (`OLLAMA_NUM_PARALLEL=1`) and tuning sensitivity.
- PREFENSE (IEEE CAI 2026) — additional context can degrade model
  judgement on some tasks.
