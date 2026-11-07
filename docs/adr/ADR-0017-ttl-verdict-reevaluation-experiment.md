# ADR-0017: TTL verdict re-evaluation and retrospective provenance

**Status:** Accepted / TTL reuse and re-evaluation validated on controlled runs;
severity calibration pending
**Date:** 2026-11-06
**Related:** ADR-0015, ADR-0016, REV-1, SEV-1 variant B

**Protocol note:** ADR-0018 supersedes numeric confidence for new events with
categorical evidence-based confidence and assigns severity escalation to master.
The TTL/revision/provenance decisions in this ADR remain accepted. Historical
numeric events remain append-only but are excluded from the new reuse protocol.

## 1. Context

Prior verdict reuse reduced repeated triage cost but had no age bound or revision
lineage. REV-1 requires periodic re-evaluation without rewriting history. SEV-1
variant B additionally needs model confidence before any verdict-aware severity
escalation can be considered. Retrospective analysis must identify the actor,
model, prompt, overall ruleset, concrete rule, and reason for each revision.

The main 300-repository corpus was not resumed for this experiment.

## 2. Implemented candidate

- `submit_verdicts` accepts optional integer `confidence` in `0…100`. Missing,
  invalid, boolean, and out-of-range values normalize to `None` without rejecting
  the batch.
- The guided prompt anchors `80…100` to direct unambiguous evidence, `50…79` to
  strong indirect evidence, and `0…49` to weak signals with NEEDS_REVIEW preferred.
  Existing verdict rules, including the prohibition on FALSE_POSITIVE from
  incomplete evidence, are unchanged.
- Reuse considers only the latest visible verdict per fingerprint. It is accepted
  without a new journal event when its age is below `reuse_ttl` and confidence is
  present. The default is `1w`; this experiment froze `1h`.
- Expired records and legacy records without confidence return to normal triage.
  A cross-run result appends a new event with `supersedes_verdict_id` and
  `revision_reason=ttl_expired|legacy_confidence_missing`. Verdicts remain immutable
  within a run.
- `triage_verdicted` events carry confidence, actor/model, prompt SHA-256,
  scanner/rule ID, overall ruleset SHA-256, per-rule definition SHA-256 where
  resolvable, and an explicit `unavailable` status otherwise.
- Semgrep YAML and Gitleaks TOML hashes cover canonical effective definitions.
  Semgrep path-prefixed check IDs use unambiguous suffix matching. Trivy and
  built-in detector rules do not receive fabricated hashes.
- `--force-reevaluate` is deferred. It should bypass freshness while preserving
  prior verdict reads, `supersedes_verdict_id`, and `revision_reason=manual`; it is
  distinct from `--no-reuse-verdicts`.
- **Freshness amendment (2026-11-07, GD-10, not yet implemented):** matching
  `prompt_sha256` is not sufficient because scanner rules can change underneath
  an unchanged prompt. Reuse must additionally match the effective `ruleset_hash`
  recorded in §3, and must never replace a human-sourced verdict. Per-mode TTLs
  are proposed in ADR-0019 Part 5.3 but remain unadopted until measured.

Severity escalation is not enabled by this candidate.

## 3. Experiment setup

- Artifact label: `agent300review`; master project identity: `agent300`. These
  names intentionally differ only in the run ID; `project_id_for()` maps both
  phases to the same master project key, as confirmed by NDJSON.
- Repositories: the existing ten-item `REPEAT` development list.
- Mode: `guided-sched`, external research rules, parallelism 1, `reuse_ttl=1h`.
- Model: `ollama/hf.co/unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q3_K_M`,
  digest `9f11c533d43b7d1b7b9fdf7d95b25a6e31dea582bfc6c44846d9578b19b142cd`.
- Agent image: `sha256:b3ffcb9aeca54d9bda08eda97c99cfa8ad86c01125878b4b387c3a8147ae9978`.
- Guided prompt SHA-256:
  `beb25fe08311d66a7710a20d38715caf1d8d4dd5573855ae4bf1fce8180509de`.
- Review knowledge cutoff: `2026-11-06T06:44:03.327213+00:00`, excluding aborted
  prototype events. Those append-only attempts were not used in the statistics.
- Observed scan ruleset example:
  `sha256:ca5bcf5582a78bd46f5df56b7efb32528bc3a292b9d341c56330eab8a318b593`.
- Structured results:
  `experiments/tp-0001/artifacts/agent300review-reevaluation-stats.json`.

`make check` passed with 554 mcp-server tests, 148 master tests plus two
PostgreSQL skips, and 8 appsecgate-agent tests.

## 4. Results

Coverage is measured by unique `finding_id`. Raw inventory contains 1054 rows and
1016 unique IDs in the nine reports with an inventory. Duplicate fingerprints
account for the difference and are not counted as missing model verdicts.

| Repository | Unique IDs | TP | FP | NR | Confidence median | Outcome |
|---|---:|---:|---:|---:|---:|---|
| structlog | 2 | 0 | 2 | 0 | 100 | complete |
| aitextgen | 3 | 2 | 1 | 0 | 100 | complete |
| claude-code-skills | 247 | 100 | 128 | 19 | 90 | complete |
| CodeWiki | 98 | 92 | 4 | 2 | 100 | complete |
| zep | 278 | 270 | 4 | 4 | 100 | complete |
| AIWriteX | 37 | 29 | 4 | 2 | 90 | 2 failed/missing |
| bitcore | not reported | — | — | — | — | agent timeout at 1800 s |
| openbot | 193 | 82 | 96 | 15 | 95 | complete |
| overseerr | 128 | 110 | 16 | 2 | 100 | complete |
| Huatuo-Llama-Med-Chinese | 30 | 30 | 0 | 0 | 100 | complete |

Aggregate:

- 8/10 runs have complete unique-finding coverage; AIWriteX has two failed
  findings and bitcore exceeded the agent timeout.
- 1014 reported verdicts: 715 TRUE_POSITIVE, 255 FALSE_POSITIVE,
  44 NEEDS_REVIEW.
- Confidence is present for all 1014 reported verdicts: 960 in `80…100`,
  54 in `50…79`, none in `0…49`; mean 93.75, median 100.
- 1455 journal events have complete required provenance. This comprises the 1014
  reported events plus 441 bitcore events written before its timeout. The latter
  are not counted as completed report verdicts.
- Reuse candidates, reused verdicts, re-evaluations, supersedes links, baseline
  common IDs, and measured verdict drift are all zero.

## 5. Interpretation

The experiment validates additive serialization and provenance on real runs, but
**does not validate TTL reuse or re-evaluation**. The setup did not provide
eligible prior history under the selected project identities and review cutoff.
The zero counts are an invalid experiment design, not a negative TTL result. A
controlled sequential validation must not reuse this frozen cutoff because it
would hide newly written Phase A events from the next phase.

The confidence distribution is highly concentrated at the top anchor. Without
human ground truth and more low/medium examples, it cannot establish calibration
or a safe severity threshold. At this distribution `TP + confidence >= 80 →
critical` degenerates into escalating almost every TP, including false ones; it
is not a confidence-based severity decision.

The run also exposes operational follow-ups: bitcore timed out after writing 441
journal events, AIWriteX left two findings unresolved, and duplicate fingerprints
require raw-versus-unique coverage reporting. These are recorded observations, not
fixes included in this ADR.

## 6. Controlled TTL validation — rev1v3

A subsequent controlled series used `structlog` (2 findings) and `aitextgen` (3),
unique artifact labels, stable `agent300` project identity, and no knowledge
cutoff. A1 used TTL zero to create a fresh baseline. Results are in
`experiments/tp-0001/artifacts/rev1v3-validation.json` with `passed=true`.

The validation exposed and fixed two real integration bugs: empty cutoff now
normalizes to `None`, and PostgreSQL textual JSON numbers are normalized to
integer confidence before freshness evaluation. Without the latter, fresh
PostgreSQL verdicts were incorrectly treated as expired.

| Phase | Evidence | Result |
|---|---|---|
| A1 baseline | 5 new verdicts with complete coverage | pass |
| A2 fresh reuse | 5/5 reused, identical verdict/confidence, 0 LLM batches/tokens, 0 local or master verdict events | pass |
| B TTL expiration | 2 re-evaluations with `revision_reason=ttl_expired` and exact A1 supersedes IDs | pass |
| C legacy confidence | 3 re-evaluations with `revision_reason=legacy_confidence_missing` and exact append-only seed supersedes IDs | pass |

Thus the TTL/revision protocol is validated on 2 repositories, 5 reused verdicts,
and 5 new supersedes links. These numbers validate mechanics, not model quality or
confidence calibration.

## 7. Operational diagnostics

`experiments/tp-0001/artifacts/rev1-operations.json` records:

- **bitcore:** 441/958 findings in 1693 seconds, 15.63 verdicts/minute, maximum
  inter-event gap 67.7 seconds, and zero loop/restart/token-repeat log signals.
  Progress was continuous and consistent with sizing/timeout, not a detected
  loop. At this rate the full inventory requires roughly an hour, exceeding the
  1800-second agent timeout. A sizing/resume decision remains a corpus blocker.
- **AIWriteX:** both failed findings are in the same minified Monaco
  `workerMain.js`; there were 8 batch retries, 217374 total tokens, no tool
  errors, and `guided_incomplete=1`. This is an unresolved large-context/protocol
  failure and remains a corpus blocker, not a silent NEEDS_REVIEW conversion.
- **Duplicate fingerprints:** all 22 groups (38 extra raw rows) have the same
  scanner, rule ID, and exactly normalized snippet at different source lines.
  Line number is intentionally excluded from the fingerprint. No cross-scanner or
  dedup-family regression was found in these artifacts.

## 8. Remaining boundaries

1. Keep severity escalation disabled pending human ground-truth calibration and a
   separately reviewed threshold/category mapping. A stratified 100-finding review
   bundle is in `experiments/tp-0001/artifacts/rev1-confidence-review.json`;
   reliability metrics are not claimed until human labels are supplied.
2. `--force-reevaluate` remains a separate future trigger with
   `revision_reason=manual`, not part of this time-based validation.
3. Acceptance covers the TTL/revision/provenance protocol only. It does not resolve
   bitcore sizing, AIWriteX failed findings, confidence calibration, or authorize
   the main 300-repository corpus. Those require separate owner decisions.
