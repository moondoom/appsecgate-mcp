# ADR-0018 Mode A validation: spec-as-written baseline, quote_hash fix, scheduler parallelism

**Date:** 2026-11-07
**Status:** final — 9/10 repos completed with `gate_block`; bitcore remains incomplete (token budget)
**Related:** ADR-0018 (evidence-based confidence), ADR-0016 (context lanes),
ADR-0015, `docs/open-tasks.md`
**Series:** baseline `agent300adr18` (10 repos), fix `agent300fix1` (10 repos, same identity)

## 1. Goal

Validate ADR-0018 Mode A (model returns `verdict` + `confidence_level` +
`evidence_basis` + `evidence_quote`; edge verifies) on a 10-repo smoke corpus
before the main 300-repo run: verdict distribution, reuse, downgrade
behaviour, operations (batching, timeouts), and drift vs the `agent300review`
pre-ADR series.

## 2. Baseline as written: `agent300adr18`

Spec-as-written asked the model to produce `quote_hash` (SHA-256 of the raw
evidence quote) as a field of `submit_verdicts`; the edge validator compared
it against the computed hash.

Aggregate over 10 repos (`artifacts/agent300adr18-stats.json`):

- 1016 unique findings; verdicts: TP 621 / FP 145 / NR 245.
- Reused 5 (only the two smoke repos), reevaluated 1047
  (`legacy_confidence_missing`).
- **Downgraded 745/1216 (61%); 0 surviving `high`** out of 881 model attempts
  (587 cve + 262 sast + 25 secrets + 7 iac).
- Downgrade reasons: `quote_mismatch` 632, `basis_not_high_capable` 74,
  `no_absence_evidence` 39.
- 0 numeric confidence events, 0 `rejected:edge_validator`.
- Drift vs `agent300review`: 276/1011 common findings.

**What this baseline does NOT measure:** calibration. 100% of `high` verdicts
were destroyed before the validator's substantive checks, so the series
measures a spec bug, not model calibration. It is a *spec-as-written
baseline*, cited so the fix below has a citable "before".

### Operations (baseline)

- bitcore: 210/958 batches, 7.44 batches/min, scanner timeout 1800s — the
  guided batching sizing blocker reproduces.
- AIWriteX: 3 missing findings (2× minified `workerMain.js` +
  `image-designer.js`), 9 retries, 226k tokens — oversized-minified-input
  failure reproduces.
- 18 duplicate verdict groups (same rule and snippet).

## 3. Design finding: `quote_hash` ownership

ADR-0018 §3.1 said "SHA-256 of pre-redaction quote" without specifying **who
computes it**. The prompts assumed the model (the field sat next to
`evidence_quote` in `submit_verdicts`); the validator assumed the edge
(§5: "Edge проверка SHA-256 evidence_quote"). Together they required the
model to guess 64 hex chars — probability zero for any non-empty quote, so
2/2 smoke failures and 100% baseline `high` downgrades are deterministic,
not statistical.

This is the third occurrence of one pattern: the experiment measures
something other than intended (ADR-0016 salt placement measured cache-hit,
ADR-0017 wrong project_id measured absence of reuse, ADR-0018 measured model
arithmetic). The rule is now in `AGENTS.md` ("model output is for judgment,
not computation"): deterministic values are computed by the system and never
requested from the model; model judgment outputs are verified against ground
truth; smoke before baseline must catch a ~100% dominant downgrade reason.

**Fix implemented** (commit `e338f26`): `quote_hash` removed from the
`submit_verdicts` schema; the edge computes `sha256(evidence_quote)` and
checks quote-in-source (whitespace-normalized substring);
`quote_mismatch` now means "quote not found in source" — a substantive
anti-hallucination check. Redaction-vs-matching policy for secrets deferred
to a separate small ADR (see open-tasks).

## 4. Infrastructure findings (ollama host 10.0.0.222, RTX 4060 Ti 16 GB)

Measured with salted-context probes (`kv_probe.py`, artifacts
`kv-probe-*.json`; runtime notes in `runtime/llm-host.md`, not committed):

1. **`OLLAMA_NUM_PARALLEL=auto` silently gave 1 slot.** Auto sizes slots from
   the trained context (262144), so all client-side parallelism serialized on
   one slot; prefix cache hits (50–350k tok/s) masked it. Fix: explicit
   `NUM_PARALLEL=4`, `CONTEXT_LENGTH=36864` (per-slot; slots adapt to request
   `num_ctx`).
2. **Per-lane `num_ctx` caused runner thrash**: guided-sched sent lane-sized
   `num_ctx` (8k/16k/32k); ollama rebuilds the runner per distinct value —
   14 reloads in 90 minutes, each wiping the prefix cache. Fix enacts the
   ADR-0016 §8 fallback: lanes size prompts and stats only; every request
   carries constant `num_ctx=36864` (commit `8c70670`).
3. **Decode is bandwidth-saturated**: 64 t/s single stream → ~78 t/s
   aggregate at par4 (probe `kv-probe-scale16k.json`). The win of 4 slots is
   pipeline overlap and no head-of-line blocking, not raw throughput.
4. **KV q4_0 ≈ q8_0** in probes (within noise) — kept q4_0.
5. **256k maxctx works** (131k prompt prefill ~1088 tok/s, decode ~20 t/s) —
   usable for exotic cases, not for the agent.
6. **"2–4% CPU" in `ollama ps` is the idle vision encoder** (mmproj ~1.1 GB
   CPU-mapped), not compute layers (31/31 on GPU) — no perf impact for
   text-only runs.
7. **Client LLM timeout 120s was too small** for 4-slot decode (~20 t/s per
   stream → 2048-token response ≈ 100 s+): killed bitcore and zep mid-run.
   Raised to 600s and passed through `invoke-docker.sh` (commit `8c70670`).

## 5. Fix series `agent300fix1` vs baseline

Final artifact: `artifacts/agent300fix1-stats.json`. Nine repos completed with
`gate_block`; bitcore did not produce a completed report and is excluded from
the aggregate, as it was in baseline.

- 1016 unique findings; final verdicts: **TP 646 / FP 160 / NR 204**;
  6 missing/failed findings (CodeWiki 2, AIWriteX 2, openbot 2).
- Across journal events (including revisions), the model attempted `high`
  2253 times and **1753 `high` ratings survived**, versus **0 in baseline**.
- Downgrades: **296** (baseline 745), all substantive:
  `no_absence_evidence` 147, `basis_not_high_capable` 98,
  `quote_mismatch` 51 (real quote-not-in-source, versus 632 arithmetic).
- Reuse candidates 1052; reevaluated 1052: 841 `prompt_updated`,
  208 `ttl_expired`, 3 `legacy_confidence_missing`.
- 0 `rejected:edge_validator`; 0 numeric confidence events (expected in
  Mode A).
- Verdict drift on 1007 common findings: **106 (10.5%)**, expected after the
  prompt protocol change; this is not calibration evidence.
- Approximate wall comparison on four comparable mid-size repos
  (claude-code-skills, CodeWiki, zep, AIWriteX): **~37 min vs ~65 min** in
  baseline (~1.75×), despite full prompt-triggered reevaluation.

### bitcore (incomplete, separate from aggregate)

bitcore ran 62.4 minutes and stopped with
`LLM token limit exceeded: 3891787 > 2000000`. Its local append-only journal
contains 841 unique findings with verdicts (TP 401 / FP 400 / NR 40), but no
completed report; it is therefore not counted as corpus coverage. Earlier
120 s per-call and 1800 s whole-run timeouts were removed as blockers; the
remaining blocker is the 2M token budget and its interaction with partial
retries. Raising that budget is an owner decision, not an automatic fix.

## 6. Conclusions and follow-ups

- The ADR-0018 Mode A protocol is sound once deterministic fields are
  edge-computed: substantive downgrades survive, `high` survives, zero
  validator rejections.
- Human calibration (`experiment-adr18-review`, 120 blind items in
  `artifacts/adr18-confidence-review.json`) is **still not done** —
  severity escalation stays OFF until labels exist.
- Open: quote-in-source matching policy for secrets (redaction conflict),
  bitcore sizing/token budget, AIWriteX minified-input handling, corpus 300
  remains frozen until calibration.
- The next operating-point decision belongs to `scenario_add.md` GD-1…GD-9:
  current production is arm E (4×1), and acceptance must compare D (2×2)
  against both B and E rather than assuming D is an improvement.
