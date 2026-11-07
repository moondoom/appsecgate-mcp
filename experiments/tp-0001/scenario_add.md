# AppSecGate Guided Mode Redesign — Full Specification

**Document type:** implementation brief + experiment protocol
**Supersedes:** previous partial drafts (agent instructions, acceptance, full experiment)
**Related ADRs:** ADR-0015 (autonomous triage), ADR-0016 (LLM throughput), ADR-0017 (TTL reuse), ADR-0018 (evidence-based confidence)
**Date:** 2026-11-07
**Status:** draft for implementation

---

## 0. Purpose and scope

This document replaces the scheduler-based guided mode (`guided-sched`) with a single `guided` mode whose behavior is controlled by three launch parameters and a constant context size. It defines:

- what the agent must implement (Part 1);
- a one-hour acceptance experiment that gates adoption (Part 2);
- a full exploratory experiment that maps the slot surface and produces statistics (Part 3);
- a passive statistics artifact fed by both experiments (Part 4);
- the risks and the flags that must be recorded (Part 5).

The document does not change verdict semantics, evidence rules, journal format (except additive fields in §1.3), or the frozen corpus configuration.

The 300-repository corpus is **decoupled** from this document. It is a separate delivery, gated only on parity and on two known corpus blockers (bitcore sizing, AIWriteX Monaco).

---

## Part 1 — Agent instructions

### 1.0 Invariants (never violate)

1. All LLM calls go through **LiteLLM** (`:4000/v1`) with **explicit `num_ctx`** (ADR-0016 §7). No direct ollama access in any measured run.
2. `num_ctx` is a **constant** = `config.llm_num_ctx` (36864). No per-lane, per-batch, or per-request overrides.
3. Slot budget: **`internal_parallel × external_p ≤ OLLAMA_NUM_PARALLEL` (=4)**. Violation is a configuration error → fail-fast at startup, before any LLM call.
4. `reuse_verdicts` remains **ON** for production runs and **OFF** in all tuning and acceptance arms (reuse confounds tuning and would hide the effect).
5. Verdict semantics (`TP` / `FP` / `NEEDS_REVIEW`), evidence rules, and journal format are unchanged except for the additive fields in §1.3.
6. `make check` green before and after implementation.
7. **Context overflow and timeout are model-failure signals, not pending states.** A finding that the model cannot judge because the prompt would exceed `num_ctx`, or because the call exceeds the failure timeout, is written as `NEEDS_REVIEW` with `failure_reason` and a comment (§1.3). This is a deliberate change to ADR-0015 §4 and must be recorded there, not only here.

### 1.1 Removals (dead code after ADR-0016 §12)

Remove entirely:

- the finding-cost classifier (ADR-0016 §8.1) and all dependents;
- per-lane `num_ctx` in `_triage_chunk`, reload triggers, `lane_underestimated` as a control signal;
- lane-affinity sorting as a slot-packing mechanism;
- `agent_mode=guided-sched` as a separate mode; delete `agent/guided_sched.py` or rename to `agent/pipeline.py` and fold into `guided`.

Keep as **telemetry only** (not control):

- `lane_*` counters — predicted vs actual prompt length, used in statistics (Part 4).

### 1.2 Mode redesign

There is **one** batched agent mode: `guided`. Scheduler mode is gone. The knobs the scheduler owned become parameters of `guided`.

**Agent parameters (env / CLI):**

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `agent_mode` | enum | `guided` | `free` / `guided` |
| `internal_parallel` | int | 2 | in-flight batches inside one process |
| `batch_sort` | enum | `mode_major` | `mode_major` / `none` |
| `num_ctx` | int | 36864 | constant; from `APPSECGATE_LLM_NUM_CTX` |
| `reuse_verdicts` | bool | true | unchanged |
| `APPSECGATE_LLM_FAILURE_TIMEOUT_S` | int | 600 (provisional) | per-call failure timeout; recalibrated in Part 3.5 (see 1.3.2) |

**External `p` is not an agent parameter.** It is the number of processes; the agent does not know it. Invariant 1.0.3 is enforced by the launcher (wrapper / Makefile / CI), not inside the agent.

**Sorting semantics:**

- `mode_major`: all batches of one mode (sast / secret / sca / iac) are contiguous; within a mode, deterministic order by fingerprint for reproducibility. Shared prefix = system + guided template + per-mode preamble (ADR-0018 §6), so mode-major maximizes prefix-cache hits.
- `none`: natural inventory order.
- Sorting by prompt length is **not** implemented — with fixed `num_ctx` it does not pack slots and would scramble mode waves.

**Parameter surface:** the only way to change concurrency is the pair `(internal_parallel, external_p)` on the line `internal × external ≤ 4`. Experiment arms use (1,1), (1,2), (1,4), (2,1), (2,2), (4,1). Other satisfying points, such as (1,3) and (3,1), are valid configurations even though they are not required arms; only a product above 4 is a configuration error.

### 1.3 Journal schema changes (additive)

#### 1.3.1 Model-failure fields

Every verdict event gains two fields:

| Field | Type | Values | Meaning |
|---|---|---|---|
| `failure_reason` | enum or null | `context_overflow`, `timeout`, null | non-null only when `verdict=NEEDS_REVIEW` and the model did not judge |
| `failure_detail` | string or null | e.g. `"prompt_tokens+output_reserve=42110 > num_ctx=36864"`, `"elapsed_ms=120412 > timeout_ms=600000"` | diagnostic |

`NEEDS_REVIEW` is now distinguishable by origin in every downstream query: “model judged NEEDS_REVIEW” vs “model failed to judge”. This is required by the mode statistics (Part 4) and by the master escalation input (ADR-0018 §2.8); without it the statistics are ambiguous. A terminal `NEEDS_REVIEW(model_failed)` counts toward finding coverage and is **not** included in `failed_findings`; that counter is reserved for findings with no terminal verdict and for unhandled infrastructure failures.

#### 1.3.2 Failure-timeout calibration

The provisional timeout is **600 s** for implementation and the acceptance experiment. The old ADR-0016 §8.A distribution (p99 = 48 s) was measured under different concurrency and cannot justify a 90 s cap at four active slots: at ~20 t/s per stream, a legitimate 2048-token response needs ~102 s of decode alone.

After measuring calls at the actual operating point (Part 3.5), the production value is derived as:

```
timeout = p99 × 1.5, rounded up to the next 30 s
```

The derived value replaces 600 s only after verifying that calls above it are genuine failures, not legitimate long completions. Timeout and context-overflow gates are reported separately: a timeout failure does not prove that the context is too small.

#### 1.3.3 Overflow detection

The agent **tokenizes the complete outbound request before send** with the exact tokenizer for the selected model, including system prompt, tools, and template. The check is:

```
prompt_tokens + llm_max_tokens + output_safety_margin <= num_ctx
```

A request that does not fit is routed to `NEEDS_REVIEW(context_overflow)` **without an LLM call** — cheaper and avoids silent truncation (ADR-0016 §12). A response reporting actual prompt overflow or a truncation flag is treated identically. The tokenizer implementation and its model/version must be recorded; character-based estimates such as `len(json)//3` are telemetry only and cannot authorize sending. No new production dependency is allowed without an explicit owner decision.

**Split-retry is preserved.** Truncated or unparseable batches are still split and retried per ADR-0015 §4. `NEEDS_REVIEW(model_failed)` is the terminal state after retries are exhausted, not the first response to failure.

### 1.4 Telemetry via Prometheus

All metrics are collected through **Prometheus on the LLM host and the runner host**. No `nvidia-smi` sidecar; no native-API call for telemetry. This does not violate invariant 1.0.1 (which governs the LLM path, not telemetry).

#### 1.4.1 Preconditions (verify before any run)

1. **Metric names.** Confirm the actual Prometheus metric names on mgmt before the run and record them in the experiment artifact. Expected sources:
   - DCGM exporter: `DCGM_FI_DEV_SM_CLOCK`, `DCGM_FI_DEV_MEM_CLOCK`, `DCGM_FI_DEV_GPU_UTIL`, `DCGM_FI_DEV_FB_USED`, `DCGM_FI_DEV_POWER_USAGE`.
   - utkuozdemir/nvidia_gpu_exporter: `nvidia_smi_clocks_current_graphics_clock_hz`, `nvidia_smi_clocks_current_memory_clock_hz`, `nvidia_smi_utilization_gpu_ratio`, `nvidia_smi_memory_used_bytes`, `nvidia_smi_power_draw_watts`. Clock fields may be disabled by exporter default — enable them.
   - node_exporter: `node_cpu_seconds_total`, `node_memory_MemAvailable_bytes`.
2. **Scrape interval.** Default node_exporter scrape (15 s) is **too coarse** for 5-second cells. Either lower the scrape interval to **1 s on mgmt for the duration of the experiment**, or explicitly record that per-call GPU attribution is unavailable and analysis is run-level only. This decision must be in the artifact before the run; it cannot be added afterward.
3. **Missing clocks.** If the current exporter does not expose GPU or memory clock, that is a **configuration task** (enable field names in the exporter), not a reason for a sidecar. A run without clock minima is **invalid** for sustained-load and per-arm GPU analysis.

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
- `num_ctx` (assert == 36864);
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

- [ ] `agent_mode=guided-sched` does not exist; `guided` accepts `internal_parallel`, `batch_sort`, `APPSECGATE_LLM_FAILURE_TIMEOUT_S`.
- [ ] Grep: no `lane_switch`, no classifier, no per-lane `num_ctx`, no `lane_affinity`.
- [ ] Assert every outbound request has `num_ctx == config.llm_num_ctx`.
- [ ] Launcher startup check `internal_parallel × external_p ≤ OLLAMA_NUM_PARALLEL`, else fail-fast; the agent checks only that its own internal value does not exceed the slot count.
- [ ] Exact-model tokenizer pre-check including output reserve; overflow routed without an LLM call.
- [ ] `NEEDS_REVIEW(model_failed)` path implemented with `failure_reason ∈ {context_overflow, timeout}` and `failure_detail`; ADR-0015 §4 and ADR-0016 §8.4 updated.
- [ ] Journal query shows `NEEDS_REVIEW` split by `failure_reason` vs model-judged.
- [ ] Prometheus telemetry written per window, including GPU clock and memory clock minima; metric names and scrape interval recorded.
- [ ] `make check` green; parity on CodeWiki/zep (§9.2) passes.
- [ ] Smoke: `structlog` + `aitextgen` (5 findings) complete, verdicts match baseline.

---

## Part 2 — Acceptance experiment (~1 hour)

### 2.1 Purpose

Decide whether `guided` with tuning parameters is acceptable for the corpus. This is the gate. The full experiment (Part 3) is the exploration.

### 2.2 Repo set (fixed)

| Repo | Findings | Class |
|---|---|---|
| atopile | 167 | heavy |
| costrict | 115 | heavy |
| CodeWiki | 85 | small |

### 2.3 Fixed conditions

- Model: `hf.co/unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q3_K_M`.
- Agent image hash recorded.
- Per-mode prompt SHA-256 recorded (ADR-0018 §6).
- `num_ctx = 36864`, `reuse_verdicts = OFF`, `batch_sort = mode_major`.
- `APPSECGATE_LLM_FAILURE_TIMEOUT_S = 600` (provisional; Part 3.5 calibrates it at the actual operating point before any reduction).
- No knowledge cutoff.
- Prometheus scrape interval verified per §1.4.1 (1 s or explicitly documented).

### 2.4 Arms (2, to fit ~1 hour)

| Arm | internal | external | Purpose |
|---|---|---|---|
| **ACC-B** | 1 | 2 | frozen-equivalent baseline |
| **ACC-D** | 2 | 2 | target operating point |

Run ACC-B on all three repos, then ACC-D on all three. No interleaving. The parity reference for D is B: both arms must have identical batch composition and per-mode prompt SHA-256. Historical CodeWiki/zep references are checked separately under §1.5 and cannot substitute for this same-implementation comparison.

### 2.5 Budget

| Repo | ACC-B | ACC-D | Total |
|---|---|---|---|
| atopile | ~450–670 s | ~450–670 s | ~15–22 min |
| costrict | ~360–580 s | ~360–580 s | ~12–20 min |
| CodeWiki | ~180 s | ~180 s | ~6 min |
| **Total** | | | **~35–50 min** |

Overhead and scan time may push to ~60 min; the acceptance run is capped at 90 minutes. If it exceeds, the run is aborted and restarted with the same artifact label — no partial acceptance.

### 2.6 Pre-registered gates

Written into the experiment artifact **before** the run; applied to raw data **after**.

| Gate | Metric | Pass condition |
|---|---|---|
| **G1** | `speedup = wall(ACC-B) / wall(ACC-D)`, per repo | ≥ 1.15 → internal>1 justified |
| **G2** | ACC-D vs ACC-B, per-repo P99 latency | D not worse by > 10% |
| **G3** | verdict parity by `finding_id`, ACC-D vs ACC-B | drift = 0 |
| **G4** | `failed_findings` (no terminal verdict / unhandled infrastructure failure; terminal model-failure NR excluded) | 0 |
| **G5** | unique-finding coverage, including terminal `NEEDS_REVIEW(model_failed)` | 100% |
| **G6a** | `NEEDS_REVIEW(context_overflow)` / total findings, per arm per repo | ≤ 5%; else flag and break down by mode |
| **G6b** | `NEEDS_REVIEW(timeout)` / total findings at the provisional 600 s timeout | ≤ 1%; above this, wall-time comparisons are invalid until timeout calibration |

**G6 rationale.** The premise “32k is small for the agent” is answered by G6a, not by a mixed failure count. If `context_overflow` is non-trivial on atopile, the operating point is questionable, and the answer is not “tune the timeout” — it is either “accept NEEDS_REVIEW inflation” (a product decision) or “reconsider the context budget” (which §12 removed from the design). G6b detects serving/timeout problems independently and cannot be used as evidence about context size.

### 2.7 Decision tree

- **G1 pass, G2–G6 pass** → operating point accepted. `guided` with `internal_parallel=2`, `batch_sort=mode_major`, fixed 36864 becomes the production config. Scheduler mode removed permanently. ADR-0016 §8 marked superseded, §11 renamed to “guided tuning sweep”, §12 becomes baseline.
- **G1 fail (< 1.05)** → `internal_parallel=1`. Design collapses to frozen guided + external p + reuse + mode-major. ADR-0016 shrinks.
- **G1 ambiguous (1.05–1.15)** → run a third arm (`internal=4, external=1`) on atopile only (~10 min extra); use as tiebreaker.
- **G2 fail** → keep ACC-B; internal parallelism not adopted.
- **G6a fail, G1–G5 pass** → operating point accepted with a documented NEEDS_REVIEW inflation; a follow-up task “is 32k sufficient?” goes into the full experiment as a separate arm.
- **G6b fail** → fix/calibrate serving timeout and rerun the affected arm before interpreting wall time; this is not evidence that 32k is insufficient.
- **G3–G5 fail** → stop, root-cause, do not proceed to corpus.

### 2.8 Output

`artifacts/acceptance-guided-{run_id}.json`:

- per-arm, per-repo metrics (wall, P50/P90/P99, tokens, retries, failed, model-failure counts);
- per-gate verdict with the numbers that produced it;
- GPU/CPU/RAM windows per arm;
- one-line recommendation.

---

## Part 3 — Full experiment (exploration, no time cap)

### 3.1 Purpose

Map the `(internal × external)` surface, measure prefill and decoding per mode, produce the statistics for prefill reduction (ADR-0016 §8.5) and for the paper. It is **not** a gate; it can run alongside corpus work.

### 3.2 Repo sets (disjoint, because answers may differ)

| Set | Repos | Why |
|---|---|---|
| **Heavy** | atopile (167), costrict (115), zep (256, optional) | many batches per mode → cache amortizes; internal pipeline matters |
| **Small** | CodeWiki (85), structlog (2), aitextgen (3), + 2–3 tiny repos as available | few batches → cold-start and external overlap dominate |

Same fixed conditions as Part 2; `reuse_verdicts = OFF` in all arms.

### 3.3 Arms (all on 4 slots, `num_ctx=36864`, `batch_sort=mode_major`)

| Arm | internal | external | Isolates |
|---|---|---|---|
| **A** | 1 | 1 | sequential baseline, cold cache |
| **B** | 1 | 2 | external overlap, minimal internal |
| **C** | 1 | 4 | max repos-in-flight |
| **D** | 2 | 2 | target point |
| **E** | 4 | 1 | max internal pipeline |

- **Heavy set:** A–E.
- **Small set:** B, C, D.

**Sort sub-arm (D only, atopile):** D1 `mode_major` vs D2 `none`. D3 `mode_then_size` only if D1 vs D2 shows sorting matters at all.

**Repetition:** one run per cell. Repeat only a suspicious cell (> 10 % divergence from its pair), not the whole matrix — the raw data is re-checkable, so the second look is a slice, not a rerun.

### 3.4 Metrics

**Per repo:** wall time, total tokens, `batch_retries`, `failed_findings`, `NEEDS_REVIEW(model_failed)` split by reason, P50/P90/P99 latency per finding and per repo.

**Per call:** `ttft_ms`, `wall_ms`, `prompt_eval_duration`, `eval_duration`, `prompt_eval_count`, `completion_tokens`, `start_ts`, `end_ts`.

**Cache:** `cache_hit_rate = cache_read_tokens / prompt_tokens` (or the equivalent explicit `prompt_cache_hit_tokens` counter), per mode. If the serving path exposes no cache counter, report `cache_metrics_unavailable`; never derive cache hits from `prompt_eval_count`. Cold-start is reported separately per mode **per slot**.

**GPU (per arm, from Prometheus):**

| Analysis | What it answers |
|---|---|
| GPU util avg/max | does higher concurrency saturate the GPU? |
| **GPU clock min** | does any arm trigger throttling? |
| **Memory clock min** | is the memory subsystem the bottleneck at high p? |
| VRAM max | do batch buffers approach 16 GiB? |
| Power avg/max | thermal headroom under the run budget |

This is the data that closes ADR-0016 §7.C (“no thermal pressure in short runs”) and feeds §9.5.

### 3.5 Timeout calibration sub-experiment (heavy set)

1. Run arm D with `APPSECGATE_LLM_FAILURE_TIMEOUT_S = 600` and `reuse_verdicts=OFF`.
2. From per-call `wall_ms`, compute p99, p99.9, and the fraction of calls above 90 s / 120 s / 180 s.
3. Derive the operating timeout as `p99 × 1.5` rounded to 30 s.
4. Verify that calls above the derived timeout are genuine failures (error, truncation, empty output), not legitimate long calls.
5. Only then replace the provisional 600 s production default; do not use the historical p99=48 s distribution to impose a 90 s cap at four active slots.

This makes the timeout “where results go into the void” empirically grounded. Result goes into ADR-0016 §14.

### 3.6 Sustained-load check

A ≥ 30-minute run at the operating point (arm D) on the heavy set, with full telemetry:

- GPU clock min and time-at-min;
- memory clock min;
- VRAM max;
- P99 TTFT and P99 inter-token latency over the run.

A sustained run that shows clock minima dropping over time invalidates the short-run results regardless of wall time. This is the failure mode the original matrices could not see.

### 3.7 Gates (applied post-hoc to raw data)

Thresholds are pre-registered in the experiment artifact before the run; they are applied to the raw data after. Arms are fixed; analysis is free.

| Gate | Comparison | Pass condition |
|---|---|---|
| **G1** | `speedup = wall(B) / wall(D)` on atopile | ≥ 1.15 → internal>1 needed; < 1.05 → drop; between → E as tiebreaker |
| **G2** | D vs C vs E, corpus wall and per-repo P99 | per-class winners allowed and expected (heavy → E, small → D or C) |
| **G3** | D1 vs D2, cache_hit_rate and wall | < 5 % cache delta and < 3 % wall delta → remove sorting |
| **G4** | winner’s per-repo P99 vs A | not worse by > 10 % |
| **G5** | verdicts by `finding_id`, winner vs B (same batch composition and prompt SHA) | drift = 0 on CodeWiki/structlog |

### 3.8 Out of scope

- Mode B / `file_verified` / `reachability_verified` (ADR-0018 §8) — not enabled.
- Escalation — disabled.
- 300-repo corpus — separate delivery.
- Changing verdict semantics, evidence rules, journal format (except §1.3).

### 3.9 Artifacts

- `runtime/guided-tuning-{run_id}.json` — raw per-call logs (arms A–E, D1/D2).
- `artifacts/guided-tuning-summary.json` — aggregates + G1–G5 verdicts.
- `artifacts/gpu-per-arm.json` — GPU util / VRAM / clock / power per arm, per window.
- `artifacts/model-failure-breakdown.json` — `NEEDS_REVIEW(model_failed)` by reason and mode.
- `artifacts/timeout-calibration.json` — call-duration distribution, derived timeout.
- ADR-0016 §14 “Tuning sweep (guided, fixed ctx)” — tables and operating-point decision.

---

## Part 4 — Statistics artifact (passive, no gates)

Collected from the arms above and from any production run. Input for ADR-0016 §8.5 (prefill reduction: template reuse, batch size) and for the paper. **No pass/fail — this is a report.**

### 4.1 Mode breakdown

Per mode (sast / secret / sca / iac) and per repo class (heavy / small):

| Field | Source |
|---|---|
| batches per mode per repo class | run logs |
| `prompt_tokens` p50 / p90 / p99 | run logs |
| `completion_tokens` p50 / p90 / p99 | run logs |
| prefill s / batch | `prompt_eval_duration` |
| decode s / batch | `eval_duration` |
| cold-start cost per mode (first batch) | first-batch subset |
| share of batches ≤ 16k / ≤ 32k | run logs |

### 4.2 Model-failure breakdown

`NEEDS_REVIEW(model_failed)` per mode, split by `failure_reason` (`context_overflow` / `timeout`). This is the direct measurement of “is 32k small?”. If `context_overflow` concentrates in one mode, that is the input for prefill reduction in that mode — not for increasing `num_ctx`, which would break the fixed-context design.

### 4.3 Cache analysis

Per mode, per arm (D1 vs D2):

- `cache_hit_rate` overall and excluding cold-start;
- amortization: how many batches per mode are needed before the cache pays back;
- cold-start tax per mode (first batch always a miss).

This shows where the shared-prefix strategy actually pays. For tiny repos (2–3 batches per mode), it may never pay — that is an expected result, not a defect to fix.

### 4.4 Shared-prefix tokenization

The shared prefix is system + guided template + per-mode preamble (ADR-0018 §6). Its **token count** comes from the tokenizer, not an estimate. This number, not a guess, is what sets the cache ceiling.

---

## Part 5 — Risks and flags

1. **Protocol change, not tuning change.** ADR-0015 §4 says failed findings stay pending; converting them to `NEEDS_REVIEW(model_failed)` is a deliberate reversal. It is defensible (honest degradation, auditable `failure_reason`) but must be written into ADR-0015 §4, not only into ADR-0016 — otherwise two ADRs contradict each other in the same document set.

2. **NEEDS_REVIEW inflation is the real risk.** If 32k is genuinely small, G6 fails on heavy repos and the operating point is accepted with a large `NEEDS_REVIEW` count. That is a product decision (human review load), not a performance one. The acceptance gate measures it; the decision to accept the inflation belongs to the owner.

3. **`failure_reason` must be in the journal schema**, not only in logs. Otherwise the mode statistics (Part 4) and the master escalation input (ADR-0018 §2.8) cannot separate “judged NR” from “failed NR”.

4. **Clock metrics are mandatory and may require exporter configuration.** If the current Prometheus exporter does not expose GPU or memory clock, enable the field names — do not add a sidecar and do not skip the metric. A run without clock minima is invalid for sustained-load and per-arm GPU analysis.

5. **Scrape interval.** Default 15 s is too coarse for 5-second cells. Either lower to 1 s on mgmt for the experiment, or record explicitly that per-call GPU attribution is unavailable and analysis is run-level only. This decision cannot be added after the run.

6. **`internal` vs `external` may have different winners per repo class.** This is a normal result, not a failure of the experiment. `internal_parallel` should be a launch parameter, not a global default, if G2 shows heavy → E and small → D or C.

7. **Small repos may show nothing in tuning.** With few batches, internal parallelism has little to pipeline. Small repos belong to arms B/C/D and to cold-start analysis, not to G1. Extrapolating G1 from heavy to small would be wrong.

8. **Acceptance is capped at 90 minutes.** If the run exceeds, it is aborted and restarted with the same artifact label — no partial acceptance.

---

## Part 6 — Artifact index

| Artifact | Part |
|---|---|
| `artifacts/acceptance-guided-{run_id}.json` | 2.8 |
| `runtime/guided-tuning-{run_id}.json` | 3.9 |
| `artifacts/guided-tuning-summary.json` | 3.9 |
| `artifacts/gpu-per-arm.json` | 3.9 |
| `artifacts/model-failure-breakdown.json` | 3.9 / 4.2 |
| `artifacts/timeout-calibration.json` | 3.5 |
| `artifacts/mode-breakdown.json` | 4.1 |
| `artifacts/cache-analysis.json` | 4.3 |
| ADR-0015 §4 update | 1.0.7 / Part 5 flag 1 |
| ADR-0016 §8 superseded, §11 renamed, §12 baseline, §14 new | Part 2.7 / 3.9 |

---

**End of document.**