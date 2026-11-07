# ADR-0020: Guided full experiment, statistics, and backlog

**Document type:** experiment protocol + statistics specification
**Continues:** ADR-0019 (design invariants, guided mode spec, acceptance experiment)
**Related ADRs:** ADR-0015, ADR-0016, ADR-0017, ADR-0018
**Date:** 2026-11-07
**Status:** Proposed; split from ADR-0019 after it exceeded the 60 KB hard ceiling (test_file_size_limits). Section numbering continues ADR-0019 Parts 3-10 unchanged.

---

## Part 3 — Full experiment (exploration, no time cap)

### 3.1 Purpose

Map the `(internal × external)` surface, measure prefill and decoding per mode, produce the statistics for prefill reduction (ADR-0016 §8.5) and for the paper. It is **not** a gate; it can run alongside corpus work.

### 3.2 Repo sets (disjoint, because answers may differ)

| Set | Repos | Why |
|---|---|---|
| **Heavy** | atopile (167), costrict (115), zep (256, optional) | many batches per mode → cache amortizes; internal pipeline matters |
| **Small** | CodeWiki (85), structlog (2), aitextgen (3), + 2–3 tiny repos as available | few batches → cold-start and external overlap dominate |

Same fixed conditions as ADR-0019 Part 2; `reuse_verdicts = OFF` in all arms.

### 3.3 Arms (all on 4 slots, `num_ctx=36864`, `batch_sort=mode_major`)

| Arm | internal | external | Isolates |
|---|---|---|---|
| **A** | 1 | 1 | sequential baseline, cold cache |
| **B** | 1 | 2 | external overlap, minimal internal |
| **C** | 1 | 4 | max repos-in-flight |
| **D** | 2 | 2 | target point |
| **E** | 4 | 1 | max internal pipeline |
| **F** | 2 | 1 | internal pipeline without external overlap |

- **Heavy set:** A–E; **F additionally on atopile** to isolate internal pipeline from external overlap.
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

### 3.5 Timeout and per-finding-cap calibration (heavy set)

1. Run arm D with `APPSECGATE_LLM_FAILURE_TIMEOUT_S = 600` and `reuse_verdicts=OFF`.
2. From per-call `wall_ms`, compute p99, p99.9, and the fraction of calls above 90 s / 120 s / 180 s.
3. Derive the deployment timeout as `p99 × 1.5` rounded to 30 s.
4. From cumulative **reserved-token charges per finding** (never provider usage), compute p95/p99 and derive `per_finding_cap = p95 × 1.5`. The distribution already includes actual retries and splits, so no additional split-depth multiplier is applied.
5. Verify that calls above the timeout are genuine failures and findings above the cap are genuine budget blowouts (repeated splits/retries/verbose completions), not legitimate complex findings.
6. Only then replace the provisional reference values; do not use the historical p99=48 s distribution to impose a 90 s cap at four active slots. A different deployment repeats this derivation instead of copying values.

This grounds both timeout and per-finding cap in the same operating-point data. Results go into ADR-0016 §14 and `artifacts/timeout-calibration.json`.

### 3.6 Sustained-load check

A ≥ 30-minute run at the operating point (arm D) on the heavy set, with full telemetry. **This belongs only to the full experiment and is not part of the 90-minute acceptance budget.**

- GPU clock min and time-at-min;
- memory clock min;
- VRAM max;
- P99 TTFT and P99 inter-token latency over the run.

A sustained run that shows clock minima dropping over time invalidates the short-run results regardless of wall time. This is the failure mode the original matrices could not see.

### 3.7 Gates (applied post-hoc to raw data)

Thresholds are pre-registered in the experiment artifact before the run; they are applied to the raw data after. Arms are fixed; analysis is free.

| Gate | Comparison | Pass condition |
|---|---|---|
| **G1** | `speedup = wall(B) / wall(D)` on atopile | ≥ 1.15 → D justified over B; < 1.05 → drop; between → E/F as distribution tiebreakers |
| **G2** | D vs C vs E, corpus wall and per-repo P99 | per-class winners allowed and expected (heavy → E, small → D or C) |
| **G3** | D1 vs D2, cache_hit_rate and wall, **same-session arms only** | < 5 % cache delta and < 3 % wall delta → remove sorting |

G3 is applied only to same-session arms. Cross-session deltas are reported
as context, not as gate evidence.
| **G4** | winner’s per-repo P99 vs A | not worse by > 10 % |
| **G5** | verdicts by `finding_id`, winner vs B (same batch composition and prompt SHA) | drift = 0 on CodeWiki/structlog |

If `cache_metrics_unavailable`, G3 uses **wall delta only** (<3%) and reaches no conclusion about prefix-cache efficiency. Sorting is kept by default; removing it requires a later experiment with explicit cache counters.

### 3.8 Out of scope

- Mode B / `file_verified` / `reachability_verified` (ADR-0018 §8) — not enabled.
- Escalation — disabled.
- 300-repo corpus — separate delivery.
- Changing verdict semantics, evidence rules, journal format (except ADR-0019 §1.3).

### 3.9 Artifacts

- `runtime/guided-tuning-{run_id}.json` — raw per-call logs (arms A–F as applicable, D1/D2).
- `artifacts/guided-tuning-summary.json` — aggregates + G1–G5 verdicts.
- `artifacts/gpu-per-arm.json` — GPU util / VRAM / clock / power per arm, per window.
- `artifacts/model-failure-breakdown.json` — `NEEDS_REVIEW(model_failed)` by reason and mode.
- `artifacts/timeout-calibration.json` — call-duration and reserved-token distributions, derived timeout and per-finding cap.
- ADR-0016 §14 “Tuning sweep (guided, fixed ctx)” — tables and operating-point decision.

### 3.10 Portability validation (P1, after reference acceptance)

Run the same pipeline on a second deployment profile (larger GPU or larger
model), deriving every parameter under ADR-0019 §1.6 instead of copying the reference
profile.

| Check | Pass condition |
|---|---|
| P1 | Launcher fails fast when `internal × external > verified_num_parallel_max`, checked against the loaded runner |
| P2 | Derived `num_ctx` is recorded and differs when the profile requires it; no hardcoded 36864 |
| P3 | Exact tokenizer active; `context_overflow ≤5%` |
| P4 | `budget_exhausted / total ≤5%`; otherwise cap is mis-calibrated |
| P5 | CodeWiki parity versus that profile's same-code baseline = 0 drift among judged findings |
| P6 | `NEEDS_REVIEW(timeout) ≤1%` after local calibration |
| P7 | GPU and memory clock minima recorded |
| P8 | Cross-model quality on the human-labeled subset meets the pre-registered per-mode quality thresholds; operational parity alone cannot pass this check |

Artifact: `artifacts/portability-validation.json`. This is not a second
acceptance: acceptance validates the process on the reference profile;
portability proves that no reference-profile value leaked into the design.

**P8 measures judgment quality, not stability.** The initial human-review
source is `artifacts/adr18-confidence-review.json` (120 blind items); labels
must exist before P8 can run. For each model, report per-mode accuracy and
TP/FP/NR confusion against human labels. The owner pre-registers the minimum
per-mode quality and the maximum allowed regression versus the reference model
before seeing model identities or results. No fixed X% is invented in this
ADR. A weaker model can have zero drift against itself and still fail P8;
without human labels, universality is limited to operational portability and
must not be described as verdict-quality portability.

---

## Part 4 — Statistics artifact (passive, no gates)

Collected from the arms above and from any production run. Input for ADR-0016 §8.5 (prefill reduction: template reuse, batch size) and for the paper. **No pass/fail — this is a report.** The artifact generator filters events by `agent_mode` structurally: free-mode events cannot enter guided aggregates by convention or accident.

### 4.1 Mode breakdown

Per mode (sast / secret / sca / iac) and per repo class (heavy / small):

| Field | Source |
|---|---|
| batches per mode per repo class | run logs |
| `prompt_tokens` p50 / p90 / p99 | run logs |
| `completion_tokens` p50 / p90 / p99 | run logs |
| prefill s / batch | `prompt_eval_duration` |
| decode s / batch | `eval_duration` |
| cold-start cost per mode (first batch on each slot) | first-batch-on-slot subset |
| share of batches ≤ 16k / ≤ 32k | run logs |

### 4.2 Model-failure breakdown

`NEEDS_REVIEW(model_failed)` per mode, split by `failure_reason` (`context_overflow` / `timeout` / `llm_error` / `budget_exhausted`). Only `context_overflow` answers whether the derived context is small. If it concentrates in one mode, that is input for prefill reduction in that mode — not for increasing `num_ctx` blindly.

Operational counters in the same passive report: `token_repeat_limit_reached`, `timed_out_calls`, split depth distribution (current maximum 5), and provider-reported versus unavailable usage. Free-mode iterations/restarts/compactions are structurally excluded from guided metrics. Until file-linked verification, every `quote_mismatch` carries `classification_unavailable=true` and remains a model evidence error; no protocol-limitation relabeling is allowed (§4.6).

### 4.3 Cache analysis

Per mode, per arm (D1 vs D2):

- `cache_hit_rate` overall and excluding cold-start;
- amortization: how many batches per mode are needed before the cache pays back;
- cold-start tax per mode per slot (the first batch on a slot is a miss).

This shows where the shared-prefix strategy actually pays. For tiny repos (2–3 batches per mode), it may never pay — that is an expected result, not a defect to fix.

### 4.4 Shared-prefix tokenization

The shared prefix is system + guided template + per-mode preamble (ADR-0018 §6). Its **token count** comes from the tokenizer, not an estimate. This number, not a guess, is what sets the cache ceiling.

### 4.5 Reuse savings

Per mode report `reused_verdicts`, provider-known `reuse_saved_tokens`, and reuse/revision reason distributions. Unknown usage is null, not an estimate. This feeds per-mode TTL evaluation.

### 4.6 Quote-mismatch isolation

Arithmetic hash mismatches were eliminated by the ADR-0018 fix. Until file-linked quote verification exists, the validator cannot distinguish quote-not-in-snippet from quote-from-another-file. Therefore **all remaining mismatches are counted as model evidence errors**, with `classification_unavailable=true` in the artifact. Reclassification as a protocol limitation is allowed only after file-linked verification proves the quote's actual source; silently treating every mismatch as a spec defect would hide real model errors.

---

## Part 5 — Agent behavior audit and improvement backlog

This audit supplements the acceptance experiment. Priorities do not silently
change the acceptance gates: P0 items required for that gate are already in
ADR-0019 Part 1 and GD-1…GD-9; the remaining items enter through `docs/open-tasks.md`.

### 5.1 Launch and isolation

Current controls: read-only project, LiteLLM-only LLM path, scanner 900 s,
agent 7200 s, container wall 130m, external p=1 in fix1.

| Improvement | Priority |
|---|---|
| Pre-flight fail-fast: `internal × external ≤4`, constant `num_ctx`, model digest, Prometheus metric names and scrape interval | P0 |
| Adaptive run timeout `base + per_finding × N`, initially base≈1800 s and per-finding≈2–3 s, validated from run data | P1 |
| Checkpoint/resume after each accepted batch so timeout does not restart a repository from scratch | P0 for corpus, P1 now |
| Keep per-call and whole-run timeouts as separate parameters and report which fired | P1 |

### 5.2 Scan and inventory

Current: full scan before LLM, pages of 50, deterministic mode classification
and `inventory_hash`.

| Improvement | Priority |
|---|---|
| Inventory pages of 200–500 after measuring MCP payload sizes | P1 |
| Inventory cache keyed by `(inventory_hash, ruleset_hash)`; any scanner-rule change invalidates it | P1 |
| Sub-classification `sca_manifest`/`sca_lockfile` and `sast_snippet`/`sast_file_needed` for batch planning | P1 |
| Early token-budget estimate before triage | P2 |

### 5.3 Master knowledge and reuse

Current: TTL 1w, per-mode prompt hash, append-only revisions. The audit found
that scanner rules can change while the prompt stays constant, so prompt hash
alone is insufficient.

| Improvement | Priority |
|---|---|
| **Add `ruleset_hash` to the reuse freshness condition** | **P0 correctness** |
| Candidate per-mode TTLs: CVE 24–48 h, secrets/SAST 7d, IaC 3d; calibrate before adoption | P1 |
| Log `reuse_reason` and provider-known `reuse_saved_tokens` per mode | P1 |
| Reuse only `verdict_source=model`; never overwrite human verdicts | P1 |

### 5.4 Batch planning

Current: batch 8, `len//3+4000` telemetry, `(mode,lane)` sort, internal 4 in
fix1. Exact tokenization and pre-flight split are P0 in GD-3, not optional
improvements.

| Improvement | Priority |
|---|---|
| Per-mode batch-size candidates (secret 8–12, CVE 12–16, SAST 6–8, IaC 8–10), adopted only after parity/overflow measurements | P1 |
| Capacity-aware packing by exact tokens, target≈28k and hard limit below `num_ctx − output_reserve` | P1 |
| Explicit stable `(mode,lane,fingerprint)` order; lane never controls request context | P1 |
| Pre-flight split before sending whenever the exact request exceeds capacity | P0 |

### 5.5 Batch lifecycle

Current: temperature 0, max output 2048, four LLM iterations, no SDK retry,
provisional 600 s call timeout.

| Improvement | Priority |
|---|---|
| LLM call errors are batch-fatal and run continues (GD-9) | P0 |
| Calibrate timeout from arm-D distribution before reducing 600 s (ADR-0019 §0.1.1) | P0 |
| Evaluate one LiteLLM transport retry for 5xx/connection-reset only | P1 |
| Candidate `max_tokens = batch_size × 150 + 256`; validate against verdict truncation | P1 |
| Six iterations for SAST/IaC versus four for secrets/CVE, only after evidence-use measurement | P2 |
| A/B `think=true` for SAST as a separate quality experiment | P2 |

### 5.6 Verdict acceptance and edge validation

Current: schema/pending/duplicate checks, edge hash, substantive downgrades.

| Improvement | Priority |
|---|---|
| Mark all quote mismatches `classification_unavailable=true` until file-linked verification; no speculative protocol-limitation label | P0 |
| Extend quote verification to files linked by `read_event_id` before Mode B | P1 now, P0 for Mode B |
| Cross-field consistency for FP/high and absence evidence | P1 |
| `read_event_id` linkage for `file_verified` | P2 |

### 5.7 Retry and errors

Current: split depth 5, pending failures, token-repeat special case.

| Improvement | Priority |
|---|---|
| Terminal `NEEDS_REVIEW(model_failed)` after retries with reason and detail | P0 |
| Evaluate split depth 3 versus current 5; measure retries and coverage (ADR-0019 §0.1.8) | P1 |
| Per-finding retry after split isolation | P1 |
| Deterministic per-finding reserved-token cap plus provider-known usage telemetry (ADR-0019 §1.3.4) | P0 |
| **Timeout circuit breaker:** proposed `timed_out_calls_in_window ≥5` within one repo makes the affected batch terminal `NEEDS_REVIEW(timeout)` and continues the run; no global abort. Reserved charges are retained, but timeout takes precedence over `budget_exhausted`. Window and threshold are recorded in `artifacts/model-failure-breakdown.json` | P1 |
| Count `token_repeat_limit_reached` in passive statistics | P2 |

### 5.8 Run completion

Current: gate, report, sync, 2M token budget in the frozen corpus config.
Target: per-finding cap in ADR-0019 §1.3.4; 2M is a warning threshold only.

| Improvement | Priority |
|---|---|
| Idempotent sync retry using append-only event IDs | P1 |
| Completed report always includes per-finding `budget_exhausted` counts; no run-level `budget_partial` or budget abort | P1 |
| Split `sync_error` (results exist) from `mcp_error` (no results) | P1 |

### 5.9 Free mode

Free mode keeps its existing tools and iteration/restart/compaction limits.
All artifacts carry `agent_mode`; free-mode metrics never enter guided
statistics.

## Part 6 — Deterministic CVE pre-fetch

### 6.1 Rationale

ADR-0016 §8.A found `evidence_reads≈0`; models rarely ask for the facts they
need. Version-range membership and dependency classification are deterministic
computations and must not be delegated to the model. CVE batches should
therefore receive compact deterministic evidence instead of relying on
model-generated SQL or full manifest dumps.

### 6.2 Pre-fetch blocks

**Block 1 — CVE facts** from read-only, cutoff-gated master views:

- CVE/GHSA ID, CVSS, source, cutoff and affected range;
- installed version and deterministic `in_range` result;
- fixed version and already-fixed result;
- direct/transitive and prod/dev classification when available;
- concise vulnerable-function description;
- semver matcher name/version and source-snapshot disagreement flag.

**Block 2 — similar human-confirmed verdicts** for the same
CVE/package/ecosystem, sanitized and explicitly labeled “historical evidence,
not authoritative”. The model must provide its own basis; copying a historical
basis without local evidence is rejected by the edge.

### 6.3 Responsibility split

| Question | Owner |
|---|---|
| Version in range / already fixed / direct or dev classification | deterministic matcher and lockfile facts |
| Component vulnerable | LLM with `manifest_version_match` |
| Reachability | LLM `reachability_unverified` → medium in Mode A |
| Historical verdict applies | LLM with independent local basis |
| Version out of range FP | deterministic `version_out_of_range` |
| Dev/transitive scope downgrade | policy `dependency_scope_only`, medium by default |

Proposed ADR-0018 additions: `version_out_of_range` is FP-allowed and
high-capable for deterministic exclusion; `dependency_scope_only` is not
high-capable and requires an explicit organizational policy. They are not
active until the ADR-0018 amendment and validator tests.

### 6.4 Risks

Historical verdict anchoring, cutoff correctness, semver-library correctness,
Trivy/master snapshot disagreement, and organizational dev-scope policy are
recorded explicitly. Master-unavailable pre-fetch is best-effort with a
warning, never fabricated evidence. No package-specific hardcoded allowlists.

### 6.5 Measurement arm before integration

Run only deterministic extraction on existing CVE findings, without LLM:
compute `in_range`, dependency scope and already-fixed, then compare with
existing verdicts and human labels where available. Artifact:
`artifacts/cve-deterministic-prefetch.json`.

Integration is justified if deterministic signals explain **≥30–40% of CVE
FPs**; below **10%** the added complexity is rejected. Between those values the
owner decides from error modes and token savings. This arm is orthogonal to
slot/context tuning and may run in parallel with acceptance.

## Part 7 — Master-tools removal from guided

### 7.1 Rationale and cost

Direct `master_describe_schema` and `master_query_findings_db` calls consume
prompt budget and LLM iterations, and one finding's lookup contaminates the
shared batch context. Deterministic pre-fetch answers known questions more
reliably. Free mode retains all master tools.

### 7.2 Data-gated actions

**Executed 2026-11-07 (GD-13), provisional pending NR ablation
(`artifacts/read-project-file-ablation.json`).** Removal is confirmed only
if NR inflation is ≤10 percentage points on atopile; above that threshold
`read_project_file` is restored under a dedicated flag. The frozen corpus
config must not be finalized until this ablation is complete.
`artifacts/master-tools-usage.json`: across 40
guided runs (agent300fix1, agent300adr18, agent300review, accb/accb2/accd/acce)
master tools were called **0 times**; model evidence usage is
`read_project_file` (6232 calls) plus harness-side `get_fix_context_batch`.
No verdict depends on master calls. Therefore:

- `master_describe_schema` and `master_query_findings_db` are removed from the
  guided tool list (free mode unchanged);
- `read_project_file` is gated behind `APPSECGATE_MODE_B=1` (default off);
- the guided prompt no longer instructs master-knowledge reads and describes
  `read_project_file` as optional.

Disclosure: the GD-6/GD-7 runs executed before this change had
`read_project_file` model-visible (equivalent to Mode B on); the frozen
corpus config runs with Mode B off, so a corpus smoke must confirm NR rates
do not inflate without file reads.

Before removal, analyze fix1, agent300review and rev1v3 logs for master-call
frequency, iterations/tokens spent and verdict differences. Artifact:
`artifacts/master-tools-usage.json`.

- If usage is ≈0 and no verdict depends on those calls, remove both master
  tools from the guided tool list and keep deterministic pre-fetch.
- If usage is material, pre-fetch is mandatory before removal.
- `read_project_file` keeps its definition but is disabled in guided unless
  `APPSECGATE_MODE_B=1`; acceptance runs with Mode B off.
- ADR-0015 §3/§7 and ADR-0018 §8 are updated when the measured removal is
  executed, not presented as current behavior now.

## Part 8 — Consolidated task list

`docs/open-tasks.md` is the canonical task registry; GD identifiers are stable
and are not renumbered between review amendments. Acceptance blockers remain
GD-1…GD-9. New work from this amendment is registered there as GD-10 onward,
including `ruleset_hash`, pre-flight environment checks, CVE pre-fetch,
master-tools measurement/removal, checkpoint/resume, per-mode batching/TTL,
and partial-report/sync improvements.

## Part 9 — Risks and flags

1. **Protocol change, not tuning change.** ADR-0015 §4 says failed findings stay pending; converting them to `NEEDS_REVIEW(model_failed)` is a deliberate reversal. It is defensible (honest degradation, auditable `failure_reason`) but must be written into ADR-0015 §4, not only into ADR-0016 — otherwise two ADRs contradict each other in the same document set.

2. **NEEDS_REVIEW inflation is the real risk.** If 32k is genuinely small, G6 fails on heavy repos and the operating point is accepted with a large `NEEDS_REVIEW` count. That is a product decision (human review load), not a performance one. The acceptance gate measures it; the decision to accept the inflation belongs to the owner.

3. **`failure_reason` must be in the journal schema**, not only in logs. Otherwise the mode statistics (Part 4) and the master escalation input (ADR-0018 ADR-0019 §2.8) cannot separate “judged NR” from “failed NR”.

4. **Clock metrics are mandatory and may require exporter configuration.** If the current Prometheus exporter does not expose GPU or memory clock, enable the field names — do not add a sidecar and do not skip the metric. A run without clock minima is invalid for sustained-load and per-arm GPU analysis.

5. **Scrape interval.** Default 15 s is too coarse for 5-second cells. Either lower to 1 s on appsecgate-lab for the experiment, or record explicitly that per-call GPU attribution is unavailable and analysis is run-level only. This decision cannot be added after the run.

6. **`internal` vs `external` may have different winners per repo class.** This is a normal result, not a failure of the experiment. `internal_parallel` should be a launch parameter, not a global default, if G2 shows heavy → E and small → D or C.

7. **Small repos may show nothing in tuning.** With few batches, internal parallelism has little to pipeline. Small repos belong to arms B/C/D and to cold-start analysis, not to G1. Extrapolating G1 from heavy to small would be wrong.

8. **Acceptance is capped at 90 minutes.** If the run exceeds, it is aborted and restarted with the same artifact label — no partial acceptance.

9. **Current error handling is run-fatal and has no SDK retries.** Before GD-9, a transient LiteLLM failure or timeout can abort the whole repository run. The redesign makes call errors batch-fatal and separately evaluates one transport retry for transient 5xx/connection-reset errors; it does not silently enable retries for timeouts or invalid model output.

10. **Evidence-source limitation.** Current quote verification covers the scanner snippet, not arbitrary files read through `read_project_file`. Until file-linked verification exists, every mismatch remains a model evidence error with `classification_unavailable=true`; only a verified foreign-file quote may later be reclassified as a protocol limitation.

11. **Deterministic CVE pre-fetch is data-gated.** No integration before the measurement arm explains ≥30–40% of CVE FPs; below 10% the complexity is rejected.

12. **Master-tools removal is data-gated.** No removal before usage measurement demonstrates ≈0 calls and no verdict dependency; free mode remains unchanged.

13. **Sort compatibility.** `mode_major=(mode,lane,fingerprint)` tightens the current `(mode,lane)` order without changing the meaning of mode waves. Lane remains telemetry and never alters `num_ctx`.

14. **E→D is a deliberate internal decrease.** Moving from current 4×1 to 2×2 is justified only by measured wall/tail; if G2 fails against E, current E remains the operating point.

15. **Profile values must be re-derived.** Copying the 4060 Ti values (`36864`, four slots, batch 8, 2048 output, 600 s timeout, 2M warning) to another GPU/model is a configuration error. The actual loaded-runner slot count overrides the theoretical maximum.

16. **Operational portability is not quality portability.** Missing tokenizer/tool-calling/reasoning/completion fields defer acceptance. A different model is not accepted for quality-sensitive production until P8 has human labels and pre-registered per-mode quality thresholds.

---

## Part 10 — Artifact index

| Artifact | Part |
|---|---|
| `profile-{model}.json` | 1.6 / 2.3 (mandatory model input) |
| `artifacts/acceptance-guided-{run_id}.json` | 2.8 |
| `runtime/guided-tuning-{run_id}.json` | 3.9 |
| `artifacts/guided-tuning-summary.json` | 3.9 |
| `artifacts/gpu-per-arm.json` | 3.9 |
| `artifacts/model-failure-breakdown.json` | 3.9 / 4.2 |
| `artifacts/timeout-calibration.json` | 3.5 (timeout + per-finding cap) |
| `artifacts/portability-validation.json` | 3.10 |
| `artifacts/mode-breakdown.json` | 4.1 |
| `artifacts/cache-analysis.json` | 4.3 |
| `artifacts/reuse-savings.json` | 4.5 / 5.3 |
| `artifacts/cve-deterministic-prefetch.json` | 6.5 |
| `artifacts/master-tools-usage.json` | 7.2 |
| ADR-0015 §3/§4/§7 updates | 1.0.7 / 7.2 |
| ADR-0016 §8 superseded, §11 renamed, §12 baseline, §14 new | ADR-0019 Part 2.7 / 3.9 |
| ADR-0018 §4.3 basis additions | 6.3 |

---

**End of document.**