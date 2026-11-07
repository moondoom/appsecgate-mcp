# ADR-0019: Guided mode redesign and operating-point acceptance

**Document type:** implementation brief + experiment protocol
**Supersedes:** previous partial drafts (including `experiments/tp-0001/scenario_add.md`)
**Related ADRs:** ADR-0015 (autonomous triage), ADR-0016 (LLM throughput), ADR-0017 (TTL reuse), ADR-0018 (evidence-based confidence)
**Date:** 2026-11-07
**Status:** Proposed; adoption is gated by Part 2 acceptance

---

## 0. Purpose and scope

This document replaces the scheduler-based guided mode (`guided-sched`) with a single `guided` mode whose behavior is controlled by three launch parameters and a constant context size. It defines:

- what the agent must implement (Part 1);
- a one-hour acceptance experiment that gates adoption (Part 2);
- a full exploratory experiment that maps the slot surface and produces statistics (ADR-0020 Part 3);
- a passive statistics artifact fed by both experiments (ADR-0020 Part 4);
- the agent behavior audit and improvement backlog (ADR-0020 Part 5);
- deterministic CVE pre-fetch (ADR-0020 Part 6);
- data-gated master-tools removal (ADR-0020 Part 7);
- the risks and the flags that must be recorded (ADR-0020 Part 9).

The document does not change verdict semantics, evidence rules, journal format (except additive fields in §1.3), or the frozen corpus configuration.

The 300-repository corpus is **decoupled** from this document. It is a separate delivery, gated only on parity and on two known corpus blockers (bitcore sizing, AIWriteX Monaco).

## 0.1 Review dispositions and evidence (2026-11-07 amendment)

This section records where a review proposal was rejected or narrowed instead of being copied verbatim. These are design decisions, not silent omissions.

1. **A 90 s acceptance timeout is rejected; 600 s remains provisional until calibration.** ADR-0016 §8.A measured p99=48 s under different concurrency. `artifacts/kv-probe-scale16k.json` measured 21.9–36.5 t/s per stream at four concurrent requests, and live fix1 traffic was ~18–20 t/s. At 20 t/s a legitimate 2048-token response needs 102 s of decode alone, before prefill and queueing. A 90 s cap would manufacture `NEEDS_REVIEW(timeout)` and invalidate the experiment. ADR-0020 §3.5 measures the actual distribution before any reduction.
2. **`cache_hit_rate=(prompt_tokens−prompt_eval_count)/prompt_tokens` is rejected.** In `artifacts/kv-probe-par8clean.json`, cached 8195-token prompts were reported with full prompt counts and ~200k tok/s prompt processing; the formula would report zero hits precisely when the prefix cache worked. Only explicit `cache_read_tokens`/`prompt_cache_hit_tokens` counters are valid; otherwise the metric is unavailable.
3. **Exact token accounting for timed-out calls is rejected as unobservable.** In `agent/llm.py`, a timeout raises before a response exists and `_add_usage` can only sum provider-returned usage. The number of tokens generated before a timeout is therefore unknown to the agent. Provider-reported usage remains separate telemetry and `timed_out_calls` is counted separately. For budget control, §1.3.4 instead charges the deterministic prompt+output reservation to every attempt; this bounds authorized spend without claiming to know actual GPU-token consumption.
4. **A timeout-only G6 is rejected.** The current `len(json)//3` estimator is not an overflow detector. The server log already showed `truncating input prompt ... prompt=32804 ... new=16387` on a 32768 slot. Exact-model tokenization with output reserve (GD-3) is therefore mandatory before acceptance; overflow and timeout have separate gates.
5. **Not every `quote_mismatch` is a spec defect.** The arithmetic ownership bug was fixed in `e338f26`; fix1's remaining 51 mismatches are quote-not-in-snippet results. Until file-linked verification proves a quote came from another file, all mismatches remain model evidence errors with `classification_unavailable=true`; speculative reclassification as a protocol limitation is forbidden.
6. **Acceptance parity stays D versus B; arm A is not added solely as a parity baseline.** B and D have identical batch composition and prompt hashes, so verdict drift is comparable. Performance attribution is separate: G1a is design-over-frozen-B, while G1b checks D versus E at four total slots. A (1×1) remains the sequential reference in the full experiment.
7. **The concurrency invariant does not reject unlisted valid points.** Any `internal × external ≤4` is valid on the reference profile; listed arms are experiment coverage, not an allowlist. In particular (1,3) and (3,1) are legal.
8. **Split depth 3 is recorded as a P1 proposal, not an accepted change.** Current depth 5 permits repeated retry/split after the initial 8→4→2→1 sequence. Reducing it may save retries but changes failure coverage and needs measurement; it does not block acceptance.
9. **The run-level token budget is replaced, not made “free”.** A deterministic per-finding reserved-token cap bounds retries and makes maximum authorized spend predictable (`N_findings × cap`). Findings above it become terminal `NEEDS_REVIEW(budget_exhausted)`; corpus 2M is a warning threshold only. The cap accounts for authorized spend, not unobservable actual GPU tokens (§1.3.4).
10. **Deployment values are profile-derived, not universal constants.** `num_ctx`, slot count, batch size, output cap and timeout are derived for each deployment. The reference profile fixes 36864/4 slots only for acceptance; ADR-0020 §3.10 validates another profile before generalization.
11. **The profile formulas use per-layer KV sizing, not an underspecified “KV per slot”.** §1.6 sums K+V per layer with explicit geometry, SWA window and effective element size; runner-measured allocation and overhead take precedence. Theoretical slot count is only a precondition: the launcher also verifies the loaded runner's actual slot count.
12. **Reserved-cap edge cases are explicit (E1–E4).** Mode-homogeneous output reserve is divided equally (proportional weights only for any future mixed-mode batch); every retry/split adds its own reservation; timeout circuit-breaker reason takes precedence over `budget_exhausted`; calibration uses cumulative reserved charges including actual splits, not provider usage.
13. **Operational portability is not model-quality universality.** The pipeline, formulas and acceptance process are model-independent; verdict quality is not. Every model requires a recorded model profile, local calibration, and a human-labeled cross-model quality gate. Zero drift against a model's own baseline proves stability, never correctness.
14. **Exact tokenization is deferred to GD-16; a weighted-average estimator is authorized as the interim GD-3 implementation (owner decision, 2026-11-07).** The owner rejected a model-dependent tokenizer production dependency as premature optimization. GD-3 therefore ships pre-send overflow routing on a conservative chars/token estimate (`guided.py`), with pre-flight split and terminal `context_overflow` unchanged. G6a overflow rates are estimator-based until GD-16 lands; the ADR's "no estimator fallback" clause is narrowed, not removed — exact tokenization remains the target state.
15. **G3 "drift = 0" is replaced by G3' (owner decision, 2026-11-07).** The GD-6 root-cause run (ACC-B repeated as accb2, identical config) measured self-drift of 9/166 (5.4%) on atopile and 1/125 on costrict — larger than the B-vs-D cross-drift (4/167 = 2.4% and 1/125). Drift has two independent layers: scanner/inventory nondeterminism (same commit `619eda7f` produced 167 vs 166 findings, `dedup_level1` 1648 vs 1647, different `inventory_hash`) and serving nondeterminism under continuous batching at temperature 0. G3' therefore reads: parity is computed on the finding-id intersection of judged findings; pass = drift ≤ 2% with a mandatory flip-direction breakdown, and the result is interpreted against the measured self-drift noise floor of the same stack. GD-6 atopile cross-drift 2.4% marginally exceeds 2% but sits well under the 5.4% self-noise floor and is accepted by owner decision; a snapshot pins the commit, not identical scanner output. G3' tolerance of 2% is below the observed self-drift noise floor (5.4% on atopile, ADR-0016 §14.1); on the reference stand parity is therefore a **qualitative** gate: zero drift on CodeWiki, and on heavy repos drift is read against the measured noise floor, not against 2%. Quantitative parity requires majority-of-N runs, which is not available in the 90-minute acceptance budget; the 2% threshold remains in the protocol as a target for a future stand with lower scanner nondeterminism.

---

## Part 1 — Agent instructions

### 1.0 Invariants (never violate)

1. All LLM calls go through **LiteLLM** (`:4000/v1`) with **explicit `num_ctx`** (ADR-0016 §7). No direct ollama access in any measured run.
2. `num_ctx` is **one profile-derived constant for the whole run** = `config.llm_num_ctx`. No per-lane, per-batch, or per-request overrides. The reference acceptance profile derives 36864; other profiles derive their own value under §1.6.
3. Slot budget: **`internal_parallel × external_p ≤ verified_num_parallel_max`** (4 on the reference profile). Violation is a configuration error → fail-fast at startup, before any LLM call. The value is checked against the actual loaded runner, not only a VRAM formula.
4. `reuse_verdicts` remains **ON** for production runs and **OFF** in all tuning and acceptance arms (reuse confounds tuning and would hide the effect).
5. Verdict semantics (`TP` / `FP` / `NEEDS_REVIEW`), evidence rules, and journal format are unchanged except for the additive fields in §1.3.
6. `make check` green before and after implementation.
7. **Context overflow and timeout are model-failure signals, not pending states.** A finding that the model cannot judge because the prompt would exceed `num_ctx`, or because the call exceeds the failure timeout, is written as `NEEDS_REVIEW` with `failure_reason` and a comment (§1.3). This is a deliberate change to ADR-0015 §4 and must be recorded there, not only here.
8. **LLM call errors are batch-fatal, not run-fatal.** Timeout, post-retry 5xx and other call-level errors route the affected batch through retry/split and then terminal `NEEDS_REVIEW(model_failed)`; the run continues. Unhandled infrastructure failures remain run-fatal.

### 1.1 Removals (dead code after ADR-0016 §12)

Remove entirely:

- the finding-cost classifier (ADR-0016 §8.1) and all dependents;
- per-lane `num_ctx` in `_triage_chunk`, reload triggers, `lane_underestimated` as a control signal;
- lane-affinity sorting as a slot-packing mechanism;
- `agent_mode=guided-sched` as a separate mode; delete `agent/guided_sched.py` or rename to `agent/pipeline.py` and fold into `guided`.

Keep as **telemetry only** (not control):

- `lane_*` counters — predicted vs actual prompt length, used in statistics (ADR-0020 Part 4).

### 1.2 Mode redesign

There is **one** batched agent mode: `guided`. Scheduler mode is gone. The knobs the scheduler owned become parameters of `guided`.

**Agent parameters (env / CLI):**

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `agent_mode` | enum | `guided` | `free` / `guided` |
| `internal_parallel` | int | 2 | in-flight batches inside one process |
| `batch_sort` | enum | `mode_major` | `mode_major` / `none` |
| `num_ctx` | int | derived (36864 on reference profile) | constant per run; from `APPSECGATE_LLM_NUM_CTX` |
| `reuse_verdicts` | bool | true | unchanged |
| `APPSECGATE_LLM_FAILURE_TIMEOUT_S` | int | 600 (provisional reference) | per-call failure timeout; recalibrated per deployment in ADR-0020 §3.5 (see 1.3.2) |
| `APPSECGATE_PER_FINDING_TOKEN_CAP` | int | derived (§1.3.4) | cumulative reserved-token ceiling per finding |
| `APPSECGATE_MODE_B` | bool | false | enables `read_project_file` and `file_verified`; master-tool removal in ADR-0020 Part 7 is executed (GD-13) |
| `max_batch_iterations` | int | derived (4 on reference) | evidence/tool-calling budget; adjusted from the model profile's tool-calling reliability, not guessed |

**External `p` is not an agent parameter.** It is the number of processes; the agent does not know it. Invariant 1.0.3 is enforced by the launcher (wrapper / Makefile / CI), not inside the agent.

**Sorting semantics:**

- `mode_major`: key is `(mode, lane, fingerprint)`. All batches of one mode (sast / secret / sca / iac) are contiguous, lane is telemetry-only ordering within the mode, and fingerprint makes the order explicit and reproducible. This matches and tightens the current `(mode, lane)` production ordering. Shared prefix = system + guided template + per-mode preamble (ADR-0018 §6), so mode-major maximizes prefix-cache hits.
- `none`: natural inventory order.
- Sorting by prompt length outside `mode_major` is **not** implemented — with fixed `num_ctx` it does not pack slots and would scramble mode waves.

**Parameter surface:** the only way to change concurrency is the pair `(internal_parallel, external_p)` on the line `internal × external ≤ 4`. Experiment arms use (1,1), (1,2), (1,4), (2,1), (2,2), (4,1). Other satisfying points, such as (1,3) and (3,1), are valid configurations even though they are not required arms; only a product above 4 is a configuration error. Current fix1 production is **(4,1) = arm E**, not the proposed default (2,2). Moving from E to D is an explicit reduction of internal parallelism and is allowed only if the acceptance comparison shows no wall/tail regression.

### 1.3 Journal schema changes (additive)

#### 1.3.1 Model-failure fields

Every verdict event gains two fields:

| Field | Type | Values | Meaning |
|---|---|---|---|
| `failure_reason` | enum or null | `context_overflow`, `timeout`, `llm_error`, `budget_exhausted`, null | non-null only when `verdict=NEEDS_REVIEW` and the model did not judge |
| `failure_detail` | string or null | e.g. `"prompt_tokens+output_reserve=42110 > num_ctx=36864"`, `"elapsed_ms=120412 > timeout_ms=600000"` | diagnostic |

`NEEDS_REVIEW` is now distinguishable by origin in every downstream query: “model judged NEEDS_REVIEW” vs “model failed to judge”. This is required by the mode statistics (ADR-0020 Part 4) and by the master escalation input (ADR-0018 §2.8); without it the statistics are ambiguous. A terminal `NEEDS_REVIEW(model_failed)` counts toward finding coverage and is **not** included in `failed_findings`; that counter is reserved for findings with no terminal verdict and for unhandled infrastructure failures.

#### 1.3.2 Failure-timeout calibration

The provisional timeout is **600 s on the reference profile** for implementation and the acceptance experiment; other deployments derive their own provisional value rather than inheriting it. The old ADR-0016 §8.A distribution (p99 = 48 s) was measured under different concurrency and cannot justify a 90 s cap at four active slots: at ~20 t/s per stream, a legitimate 2048-token response needs ~102 s of decode alone.

After measuring calls at the actual operating point (ADR-0020 §3.5), the production value is derived as:

```
timeout = p99 × 1.5, rounded up to the next 30 s
```

The derived value replaces 600 s only after verifying that calls above it are genuine failures, not legitimate long completions. Timeout and context-overflow gates are reported separately: a timeout failure does not prove that the context is too small. Calibration also limits blast radius: under current behavior a 600 s timeout aborts the whole repository run, so one stuck call can waste ten minutes and the entire run.

#### 1.3.3 Overflow detection

The agent **tokenizes the complete outbound request before send** with the exact tokenizer for the selected model, including system prompt, tools, and template. The check is:

```
prompt_tokens + llm_max_tokens + output_safety_margin <= num_ctx
```

A request that does not fit is routed to `NEEDS_REVIEW(context_overflow)` **without an LLM call** — cheaper and avoids silent truncation (ADR-0016 §12). A response reporting actual prompt overflow or a truncation flag is treated identically. The tokenizer implementation and its model/version must be recorded; character-based estimates such as `len(json)//3` are telemetry only and cannot authorize sending. No new production dependency is allowed without an explicit owner decision. Exact tokenization (GD-3) is mandatory **before acceptance**; there is no timeout-only variant of G6a. If tokenizer approval remains pending beyond the acceptance window, acceptance is deferred; no estimator or timeout-only fallback is permitted.

**Split-retry is preserved.** Truncated or unparseable batches are still split and retried per ADR-0015 §4. `NEEDS_REVIEW(model_failed)` is the terminal state after retries are exhausted, not the first response to failure. This requires an explicit error-boundary change: LLM timeout and other call-level `LlmError` become **batch-fatal**, not run-fatal. Unhandled infrastructure errors remain run-fatal.

#### 1.3.4 Per-finding budget cap (replaces the run-level budget)

`APPSECGATE_PER_FINDING_TOKEN_CAP` limits cumulative **reserved** tokens per finding across every retry and split. A finding above the cap becomes terminal `NEEDS_REVIEW(budget_exhausted)`; the run continues. **No run-level token budget can abort a run.** Maximum authorized LLM spend is `N_findings × cap`; the frozen corpus 2M value is only a warning threshold.

The accounting unit is deterministic, not a claim about unobservable GPU consumption:

- before each call, exact tokenization yields the prompt charge;
- the output charge is the configured `llm_max_tokens` reservation, regardless of how many tokens are eventually returned;
- prompt charge is attributed to findings by their exact payload-token shares. Output reservation is divided equally within a batch because batches are mode-homogeneous and §1.6 derives one expected completion cost per mode. If mixed-mode batches are ever introduced, the reserve is instead split proportionally to `per_finding_completion[mode]`;
- retries and splits accumulate charges for their target findings, including timeouts and calls with no provider response. Each attempt reserves its own possible output, so split does not “refund” an earlier attempt.

Reserved cap is intentionally conservative under split: it can exhaust before actual provider usage would. Calibration uses cumulative reserved charges **including real retry/split behavior**, so split depth is already present in the measured distribution; no arbitrary `expected_splits` multiplier is added. G6c detects a cap that fires too often.

Reason precedence is assigned by the failure that terminated judgment, not by the later total. In particular, **timeout circuit breaker produces `NEEDS_REVIEW(timeout)`, never `budget_exhausted`**, even though all timed-out attempts remain in the reserved-charge ledger. Likewise a pre-send overflow stays `context_overflow`; budget totals cannot relabel it after the fact. G6c is evaluated only after this precedence is applied.

This gives a hard per-finding ceiling without pretending to know actual per-finding completion tokens. Provider-reported usage remains separate telemetry. The pre-flight computes `N_findings × cap` as soon as inventory is known (from cache, or immediately after scan and always before the first LLM call). Crossing the deployment warning threshold warns and continues by default; reducing batch/output size or aborting at that point requires explicit config. No mid-run abort is allowed.

### 1.4 Telemetry via Prometheus

All metrics are collected through **Prometheus on the LLM host and the runner host**. No `nvidia-smi` sidecar; no native-API call for telemetry. This does not violate invariant 1.0.1 (which governs the LLM path, not telemetry).

#### 1.4.1 Preconditions (verify before any run)

1. **Metric names.** Confirm the actual Prometheus metric names on appsecgate-lab before the run and record them in the experiment artifact. Expected sources:
   - DCGM exporter: `DCGM_FI_DEV_SM_CLOCK`, `DCGM_FI_DEV_MEM_CLOCK`, `DCGM_FI_DEV_GPU_UTIL`, `DCGM_FI_DEV_FB_USED`, `DCGM_FI_DEV_POWER_USAGE`.
   - utkuozdemir/nvidia_gpu_exporter: `nvidia_smi_clocks_current_graphics_clock_hz`, `nvidia_smi_clocks_current_memory_clock_hz`, `nvidia_smi_utilization_gpu_ratio`, `nvidia_smi_memory_used_bytes`, `nvidia_smi_power_draw_watts`. Clock fields may be disabled by exporter default — enable them.
   - node_exporter: `node_cpu_seconds_total`, `node_memory_MemAvailable_bytes`.
2. **Scrape interval.** Default node_exporter scrape (15 s) is **too coarse** for 5-second cells. Either lower the scrape interval to **1 s on appsecgate-lab for the duration of the experiment**, or explicitly record that per-call GPU attribution is unavailable and analysis is run-level only. This decision must be in the artifact before the run; it cannot be added afterward.
3. **Missing clocks.** If the current exporter does not expose GPU or memory clock, that is a **configuration task** (enable field names in the exporter), not a reason for a sidecar. A run without clock minima is **invalid** for sustained-load and per-arm GPU analysis.
4. **Cache counters.** Verify whether LiteLLM exposes `cache_read_tokens` or `prompt_cache_hit_tokens` for ollama and record the answer before the run. If absent, set `cache_metrics_unavailable`; the G3 wall-only fallback in ADR-0020 §3.7 applies and no cache-savings claim is allowed.

#### 1.4.2 Metrics (mandatory)

Per iteration window (1 s interval), joined to call windows by timestamp:

| Group | Metric | Notes |
|---|---|---|
| GPU util | avg / max | |
| VRAM | avg / max used | against 16 GiB total |
| **GPU clock** | avg / **min** / max | min is the throttling signal |
| **Memory clock** | avg / **min** / max | min is the memory-subsystem signal |
| GPU power | avg / max | already in ADR-0016 §2 |
| CPU | user / system / iowait delta | node_exporter |
| Host RAM | min MemAvailable, max MemUsed | node_exporter |

Clock minima are the new mandatory part. Util and power alone cannot distinguish “GPU idle” from “GPU throttled”.

#### 1.4.3 Per-call telemetry (agent side)

Per LLM call, write to the run journal:

- `mode`, `repo_id`, `batch_id`, `process_id`;
- `prompt_tokens` (actual), `completion_tokens`;
- `num_ctx` (assert == profile-derived `config.llm_num_ctx`);
- `prompt_eval_count`, `prompt_eval_duration` **if LiteLLM passes them**; otherwise `null` + flag;
- `cache_read_tokens` / `prompt_cache_hit_tokens` **if the serving path exposes them**; otherwise `null + cache_metrics_unavailable`. Cache hits must never be inferred from `prompt_eval_count`;
- `slot_id` when available, so cold-start is counted per mode **per runner slot**, not only once per repo;
- `ttft_ms`, `wall_ms`;
- `start_ts`, `end_ts` (for Prometheus window join);
- `reused` (bool), `revision_reason`;
- `failure_reason`, `failure_detail` (null when judged).

Per run: `reused_verdicts`, `batch_retries`, `failed_findings`, `internal_parallel`, `batch_sort`, `external_p`, number of processes, `failure_timeout_s`, Prometheus metric names and scrape interval.

**Per-call GPU attribution is approximate** (1 s granularity vs sub-second calls) and is reported as `window_overlap`, never as “per-call GPU util”.

### 1.5 Definition of done

- [ ] `agent_mode=guided-sched` does not exist; `guided` accepts `internal_parallel`, `batch_sort`, `APPSECGATE_LLM_FAILURE_TIMEOUT_S`, `APPSECGATE_MODE_B`, `APPSECGATE_PER_FINDING_TOKEN_CAP`, `max_batch_iterations`.
- [ ] Grep: no `lane_switch`, no classifier, no per-lane `num_ctx`, no `lane_affinity`.
- [ ] Assert every outbound request has `num_ctx == config.llm_num_ctx`.
- [ ] Complete `profile-{model}.json` exists before acceptance, including tokenizer, tool-calling reliability, reasoning mode, per-mode completion distribution, per-layer KV geometry and loaded-runner slots.
- [ ] Launcher startup check `internal_parallel × external_p ≤ verified_num_parallel_max`, model digest and telemetry preconditions, else fail-fast. The slot count is verified against the loaded runner through launcher/serving introspection, not only derived from VRAM and never queried by the agent through the LLM data path.
- [ ] Exact-model tokenizer pre-check including output reserve; pre-flight split; overflow routed without an LLM call.
- [ ] `NEEDS_REVIEW(model_failed)` path implemented with `failure_reason ∈ {context_overflow, timeout, llm_error, budget_exhausted}` and `failure_detail`; LLM call errors are batch-fatal; ADR-0015 §4 and ADR-0016 §8.4 updated.
- [ ] Journal query shows `NEEDS_REVIEW` split by `failure_reason` vs model-judged.
- [ ] Reuse requires matching `ruleset_hash` and never replaces human-sourced verdicts.
- [ ] Per-finding reserved-token accounting accumulates all attempts, including timeouts; provider-reported usage remains separate telemetry.
- [ ] Until file-linked verification exists, quote mismatches carry `classification_unavailable=true` and remain model evidence errors.
- [ ] Prometheus telemetry written per window, including GPU clock and memory clock minima; metric names and scrape interval recorded.
- [ ] Tests cover E1–E3: reserve distribution within a batch, charge accumulation across retry/split, timeout-over-budget precedence at circuit breaker, plus hybrid SWA/full-attention KV sizing and loaded-runner slot-count fail-fast.
- [ ] `make check` green; parity on CodeWiki/zep (ADR-0020 §9) passes.
- [ ] Smoke: `structlog` + `aitextgen` (5 findings) complete, verdicts match baseline.

### 1.6 Deployment profile and derived parameters

All deployment-specific values are **derived and recorded**, not universal
constants. Acceptance fixes one reference profile (RTX 4060 Ti 16 GiB,
gemma-4-26B-A4B, q4_0 KV). Another deployment applies the same formulas and
records its own artifact; copying reference values is a configuration error.

**`profile-{model}.json` is a mandatory acceptance input**, not optional
documentation. It records: exact tokenizer name/version, model digest and
family, tool-calling reliability (valid tool-call rate and JSON-fallback
rate), reasoning mode (`think` setting and availability), per-mode completion
distribution, model/trained context limits, per-layer KV geometry and
effective element size, and the actual loaded-runner slot count. Acceptance is
deferred while any of these fields is unknown.

Required hardware/profile inputs: VRAM, weights bytes, runtime overhead bytes,
model layer geometry, effective KV element size, trained/model context limits,
target slots, per-mode completion distribution and measured call/token
distributions.

KV sizing is **per layer**, not one average-layer multiplication:

```
ctx_l = min(ctx, swa_window_l)   # or ctx for full-attention layers
KV_slot(ctx) = 2 × Σ_l (
    n_kv_heads_l × head_dim_l × ctx_l × effective_bytes_per_elem_l
)
```

`2` is K+V. `effective_bytes_per_elem` includes quantization block scales,
padding and alignment; q4_0 is not assumed to be exactly 0.5 byte. If model
metadata and runner allocation disagree, the measured loaded-runner allocation
wins and is recorded. This hybrid formula is required for gemma-4, whose SWA
and full-attention layers have different geometry and context windows.

`overhead` is explicitly CUDA context + activation/compute/output buffers +
graph allocations + ollama runtime + loaded auxiliary components (for example
mmproj). It is measured as free VRAM after loading the target runner, not a
magic constant; metadata-only estimates are a fallback with a recorded flag.

| Parameter | Derivation |
|---|---|
| `num_ctx` | largest context within model/trained limits such that `target_slots × KV_slot(num_ctx + output_reserve)` fits `VRAM − weights − overhead` |
| `num_parallel_max` | largest `S` for which `S × KV_slot(num_ctx + output_reserve)` fits the same budget |
| `internal × external` | chosen on the line `≤ verified_num_parallel_max`, then verified against the loaded runner |
| `batch_size[mode]` | `min(20, (max_tokens // 2) // per_finding_completion[mode])` |
| `max_batch_iterations[mode]` | derived from measured evidence/tool-call depth and JSON-fallback rate; reference value 4 |
| `max_tokens` | `batch_size × per_finding_completion[mode] × safety_factor` |
| `timeout` | `p99(wall_ms on this deployment) × 1.5`, rounded to 30 s |
| `per_finding_cap` | `p95(cumulative_reserved_tokens_per_finding) × 1.5` |

The reference profile yields 4 slots and `num_ctx=36864`; those are recorded
outputs, not design invariants. Every run artifact contains all inputs,
formulas, derived values, per-layer window assumptions, measured/estimated
overhead status, and the actual loaded-runner slot count.

---

## Part 2 — Acceptance experiment (~1 hour)

### 2.1 Purpose

Decide whether `guided` with tuning parameters is acceptable for the corpus. This is the gate. The full experiment (ADR-0020 Part 3) is the exploration.

### 2.2 Repo set (fixed)

**Repo fixtures and disclaimers.** All reference repositories are public OSS
projects pinned to the snapshot recorded in
`experiments/tp-0001/fixtures/repos-snapshot.json` (`commit_sha`,
`inventory_hash`, `snapshot_date`). They are used as **workload fixtures**
because they exercise the batch/mode profile this ADR targets — not as a
security assessment. Finding counts are raw scanner output; most are expected
false positives, and none of them is a statement about the security posture of
these projects. No private/internal repository, raw infrastructure identifier,
or credential appears in this document or its artifacts. The logical lab alias
`appsecgate-lab` is explicitly allowed by the owner and is not a raw hostname.

If a repository is internal and cannot be named, it is replaced by a
stable identifier (`repo-heavy-1`, `repo-small-2`) and the mapping lives only
in `experiments/tp-0001/fixtures/private-map.json`, which is gitignored.

**Selection.** Heavy = ≥100 findings (enough batches to amortize cache and
exercise the internal pipeline); middle = 50–100 (overflow headroom);
small = ≤20 (cold-start and external overlap). CodeWiki (85) is classified as
**middle**, not small — flag 7 (few batches) does not apply to it. This set
deviates from ADR-0017 §3's ten-item list; the deviation is justified by
covering three mode concentrations (SAST-heavy, CVE-heavy, mixed) rather than
by availability.

| Repo | Findings | Class |
|---|---|---|
| atopile | 167 | heavy |
| costrict | 115 | heavy |
| CodeWiki | 85 | middle |

### 2.3 Fixed conditions

- Model: `hf.co/unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q3_K_M`.
- Complete `profile-gemma-4-26B-A4B.json` recorded (§1.6); missing model-profile fields defer acceptance.
- Agent image hash recorded.
- Per-mode prompt SHA-256 recorded (ADR-0018 §6).
- `num_ctx = 36864`, `reuse_verdicts = OFF`, `batch_sort = mode_major`.
- `APPSECGATE_LLM_FAILURE_TIMEOUT_S = 600` (provisional; ADR-0020 §3.5 calibrates it at the actual operating point before any reduction).
- No knowledge cutoff.
- Prometheus scrape interval verified per §1.4.1 (1 s or explicitly documented).

### 2.4 Arms (B/D full set, E reference on atopile)

| Arm | internal | external | Purpose |
|---|---|---|---|
| **ACC-B** | 1 | 2 | frozen-equivalent baseline |
| **ACC-D** | 2 | 2 | target operating point |
| **ACC-E** | 4 | 1 | current fix1 production reference |

Run ACC-B on all three repos, then ACC-D on all three, then ACC-E on atopile only. No interleaving. The parity reference for D is B: both arms must have identical batch composition and per-mode prompt SHA-256. Historical CodeWiki/zep references are checked separately under §1.5 and cannot substitute for this same-implementation comparison. E prevents accepting D as an improvement over B while silently regressing relative to current production.

### 2.5 Budget

| Repo | ACC-B | ACC-D | ACC-E | Total |
|---|---|---|---|---|
| atopile | ~450–670 s | ~450–670 s | ~450–670 s | ~22–33 min |
| costrict | ~360–580 s | ~360–580 s | — | ~12–20 min |
| CodeWiki | ~180 s | ~180 s | — | ~6 min |
| **Total** | | | | **~42–60 min** |

Overhead and scan time may push to ~75 min; the acceptance run is capped at 90 minutes. If it exceeds, the run is aborted and restarted with the same artifact label — no partial acceptance.

### 2.6 Pre-registered gates

Written into the experiment artifact **before** the run; applied to raw data **after**.

| Gate | Metric | Pass condition |
|---|---|---|
| **G1a** | `speedup = wall(ACC-B) / wall(ACC-D)`, per repo — **D versus frozen baseline B**, not an internal-isolation measurement | ≥ 1.15 → D justified over B |
| **G1b** | `speedup = wall(ACC-E) / wall(ACC-D)` on atopile — **internal>1 at equal total slot count (4)** | ≥ 1.05 supports D over E; 0.95–1.05 is parity; < 0.95 rejects D |
| **G2** | per-repo P99 latency, D vs B and D vs E | D not worse than either by > 10% |
| **G3** | verdict parity by `finding_id` on the id intersection, ACC-D vs ACC-B, judged findings only (see §0.1.15) | drift ≤ 2% with flip-direction breakdown, read against the measured self-drift noise floor |
| **G4** | `failed_findings` (no terminal verdict / unhandled infrastructure failure; terminal model-failure NR excluded) | 0 |
| **G5** | unique-finding coverage, including terminal `NEEDS_REVIEW(model_failed)`; `budget_exhausted` reported separately | 100% |
| **G6a** | `NEEDS_REVIEW(context_overflow)` / total findings, per arm per repo | ≤ 5%; else flag and break down by mode |
| **G6b** | `NEEDS_REVIEW(timeout)` / total findings at the provisional 600 s timeout | ≤ 1%; above this, wall-time comparisons are invalid until timeout calibration |
| **G6c** | `NEEDS_REVIEW(budget_exhausted)` / total findings, per arm per repo | ≤ 5%; above this the per-finding cap is mis-calibrated for the deployment profile |

G1a validates the design over frozen B; it cannot attribute a speedup to
internal parallelism because B uses two slots and D four. G1b compares four
slots against four slots and is the internal-versus-external distribution
check, with the caveat that D's two processes overlap different repos. G6c is
counted only after failure-reason precedence: circuit-breaker findings remain
`timeout` and cannot inflate `budget_exhausted`.

**G6 rationale.** The premise “32k is small for the agent” is answered by G6a, not by a mixed failure count. If `context_overflow` is non-trivial on atopile, the operating point is questionable, and the answer is not “tune the timeout” — it is either “accept NEEDS_REVIEW inflation” (a product decision) or “reconsider the context budget” (which §12 removed from the design). G6b detects serving/timeout problems independently and cannot be used as evidence about context size.

### 2.7 Decision tree

- **G1a/G1b pass, G2–G6 pass** → operating point accepted. `guided` with `internal_parallel=2`, `batch_sort=mode_major`, profile-derived fixed `num_ctx` becomes the production config. D is adopted over E at comparable per-repo wall because `external=2` enables corpus-level parallelism: small repos do not queue behind heavy ones — **unverified rationale (2026-11-07): D was rejected by G1b on per-repo wall and corpus-level throughput was never measured; the rationale is retained for context only and does not drive the decision**. If corpus-level parallelism is not required, E remains valid and this ADR does not mandate the move. Scheduler mode is removed permanently; ADR-0016 §8 is superseded only after this decision.
- **G1a fail (< 1.05)** → `internal_parallel=1`. Design collapses to frozen guided + external p + reuse + mode-major. ADR-0016 shrinks.
- **G1a ambiguous (1.05–1.15)** → E is the tiebreaker against D on atopile, using G1b and G2.
- **G1b or G2 fails against E** → retain E as the operating point; D is not adopted.
- **G2 fails only against B, but not E** → keep E and record that internal parallelism has no demonstrated benefit over the frozen baseline.
- **G6a fail, G1–G5 pass** → operating point accepted with a documented NEEDS_REVIEW inflation; a follow-up task “is 32k sufficient?” goes into the full experiment as a separate arm.
- **G6b fail** → fix/calibrate serving timeout and rerun the affected arm before interpreting wall time; this is not evidence that 32k is insufficient.
- **G6c fail** → recalibrate the per-finding cap for this deployment and rerun the affected arm; do not hide budget failures inside parity.
- **G3–G5 fail** → stop, root-cause, do not proceed to corpus.

### 2.8 Output

`artifacts/acceptance-guided-{run_id}.json`:

- per-arm, per-repo metrics (wall, P50/P90/P99, tokens, retries, failed, model-failure counts);
- per-gate verdict with the numbers that produced it;
- GPU/CPU/RAM windows per arm;
- one-line recommendation.

---

## Parts 3-10 — moved

The full experiment protocol, statistics artifact, behavior backlog, CVE pre-fetch, master-tools removal, risks, and artifact index now live in ADR-0020 (split after this document exceeded the 60 KB hard ceiling). Cross-references from this document to `Part 3+` or `§3.x`-`§10.x` resolve to ADR-0020.

---

**End of document.**
