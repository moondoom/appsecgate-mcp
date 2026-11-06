# ADR-0018: Evidence-based confidence and master-owned severity escalation

**Status:** Proposed
**Date:** 2026-11-06
**Related:** ADR-0015 (autonomous triage), ADR-0016 (LLM throughput),
ADR-0017 (TTL reuse/revisions/provenance and numeric legacy confidence)

## 1. Context

ADR-0017 introduced TTL reuse, revisions, and provenance, but its numeric
`confidence` field degenerated in the ten-repository `agent300review` experiment:
960 of 1014 verdicts were in `80…100`, none in `0…49`, and the median was 100.
A `TP + confidence >= 80 → critical` rule would therefore escalate almost every
TP, including false positives. Replacing numbers with labels alone would preserve
anchor bias.

Confidence must instead be a verifiable statement about the evidence type. Edge
has scanner context and can validate verdict evidence. Master additionally owns
cross-project history, human-confirmed knowledge, CVE data, policy, and optional
deployment evidence. Severity escalation therefore belongs to master, not edge.

The project is in early alpha. Numeric confidence is removed from the new
protocol without migration. Existing append-only numeric events are retained as
historical records but excluded from the new reuse protocol; they are not
rewritten or deleted.

## 2. Decision

1. Introduce `confidence_level`: `high`, `medium`, `low`, or `speculative`.
2. Require per-mode `evidence_basis` for `high` and `medium` verdicts.
3. Link high-confidence file evidence to a concrete read event, file, range, and
   quote hash.
4. Validate verdicts deterministically on edge. Invalid high confidence is
   downgraded; high without a high-capable basis after validation is a bug.
5. Use versioned per-mode prompts and record their SHA-256 in verdict events.
6. Allow FALSE_POSITIVE only with a positive-absence basis. Incomplete evidence
   remains insufficient for FP.
7. Disable severity escalation until blind human calibration. `high` is necessary
   but not sufficient.
8. **Master owns severity escalation.** Edge classifies, validates, journals, and
   synchronizes. It never sets `escalation_*` fields and never changes scanner
   severity. Master applies policy using confidence, evidence, cross-project
   history, CVE/reachability, human knowledge, and optional deployment evidence.
9. Start with cheap Mode A. Expensive file/reachability verification is a separate
   experiment because it increases prefill cost.

## 3. Data model

### 3.1. Edge `submit_verdicts` v2

| Field | Type | Requirement |
|---|---|---|
| `verdict` | `TRUE_POSITIVE`, `FALSE_POSITIVE`, `NEEDS_REVIEW` | always |
| `confidence_level` | `high`, `medium`, `low`, `speculative` | always; final after edge validation |
| `evidence_basis` | per-mode enum | required for `high` and `medium` |
| `evidence_quote` | redacted excerpt | required for `high`; recommended for `medium` |
| `source_file` | relative project path | required for `file_verified`; must match the finding |
| `start_line`, `end_line` | integer range | required for `file_verified` |
| `read_event_id` | read-event identifier | required for `file_verified` |
| `quote_hash` | SHA-256 of pre-redaction quote | required for `high` |
| `reasoning` | string | always; one to three sentences |

Numeric `confidence` is absent from new events. Validator fields are stored
separately:

- `model_confidence_level` — model output before validation;
- `confidence_level` — final level after validation;
- `model_verdict` and final `verdict`;
- `downgrade_reason`: `basis_not_high_capable`, `quote_mismatch`,
  `no_absence_evidence`, `vex_logic`, `file_verified_no_read_event`, or
  `verdict_overridden`.

This separation supports independent model and validator evaluation.

### 3.2. Master escalation records

Master derives append-only escalation decision records; it does not mutate the
source verdict event or scanner severity history.

| Field | Meaning |
|---|---|
| `escalation_decision` | `none`, `escalated`, or `blocked` |
| `escalation_basis` | evidence used: fingerprint history, CVE reachability, human labels, policy, deployment evidence |
| `escalation_policy_version` | policy version required for reproducibility |
| `edge_validator_violations` | field-level re-validation failures recorded as edge bugs |

`blocked` means “escalation not applied”; it is not a CI/security-gate block.
Edge-supplied `escalation_*` fields are rejected and audited. Master can validate
all synced field relationships. Content-level quote validation remains an edge
responsibility unless the referenced read evidence is also available to master.

## 4. Evidence basis by mode

### 4.1. SAST (Semgrep)

| Basis | Meaning | High-capable | FP-allowed |
|---|---|---|---|
| `direct_snippet` | Vulnerable call and untrusted input are visible | yes | no |
| `file_verified` | File context and sanitizer/validation were read | deferred to Mode B | yes, when sanitizer is found |
| `indirect_pattern` | Pattern matched; context unverified | no → medium | no |
| `test_or_fixture` | Test/example code | no | yes |
| `assumption` | Name/structure assumption | no → low | no |

Pattern match alone is `indirect_pattern`, never `high`. Missing sanitizer in a
snippet is not proof of TP.

### 4.2. Secrets (Gitleaks / TruffleHog)

| Basis | Meaning | High-capable | FP-allowed |
|---|---|---|---|
| `direct_snippet_credential` | Confirmed credential exposure, not a placeholder/fixture | yes | no |
| `file_verified` | File read and non-fixture context confirmed | deferred to Mode B | yes |
| `placeholder_or_example` | `changeme`, `xxxx`, `<your-key>`, documentation | no | yes |
| `test_or_fixture` | Test data | no | yes |
| `assumption` | String resembles a secret but is unverified | no → low | no |

`high` confirms exposure, not that the credential is active. Offline evidence
cannot prove credential validity. Secret excerpts are redacted before journaling.

### 4.3. CVE / SCA (Trivy)

| Basis | Meaning | High-capable | Escalation |
|---|---|---|---|
| `manifest_version_match` | Installed version is in the affected range | yes for vulnerable-component TP | limited without reachability |
| `reachability_verified` | Call path to the vulnerable function is confirmed | deferred to Mode B | allowed after calibration |
| `reachability_unverified` | No path found, but absence is not proven | no → medium | forbidden |
| `cve_reference_only` | Only CVE/package reference | no → medium | forbidden |
| `vex_upstream` | External VEX/OSV assertion with source | yes, with provenance | source-dependent |
| `manifest_absent` | All relevant manifests/lockfiles checked; component absent | yes for FP | — |

`reachability_unverified` does not change TP to NEEDS_REVIEW: vulnerable component
presence and project-specific criticality are different claims. FP with `low` is
forbidden in CVE mode. Absence in one manifest is not positive-absence evidence.

### 4.4. IaC (Trivy misconfiguration)

| Basis | Meaning | High-capable | FP-allowed |
|---|---|---|---|
| `policy_rule_direct` | Block directly violates policy | yes | no |
| `policy_rule_context` | Violation requires role/context analysis | no → medium | yes, with verification |
| `override_possible` | Variable/override can change effective config | no → medium | only with confirmed override |
| `hallucination_risk` | Rule/policy is absent from input data | no → low/speculative | no |
| `deployment_verified` | External deployment confirmation | yes, strengthens | — |

Models cannot self-report `deployment_verified` from production filenames or
comments. It requires an external trusted source. Deterministic YAML/TOML and
policy validation is preferred for direct IaC evidence.

## 5. Validation responsibilities

### 5.1. Edge validator

Before journaling:

- `high` with non-high-capable or Mode-B-deferred basis → `medium` with
  `basis_not_high_capable`;
- empty high quote → `medium`;
- `file_verified` without matching read event, file, range, or quote hash →
  `medium` with the corresponding reason;
- FP without FP-allowed basis → NEEDS_REVIEW with `no_absence_evidence`;
- CVE FP with `low` → NEEDS_REVIEW with `vex_logic`;
- speculative FP is forbidden;
- missing basis for `high`/`medium` is a protocol violation and retries the batch;
- `reachability_unverified` leaves TP unchanged but prevents escalation.

The validator never upgrades confidence. Zero high-capability violations are
allowed after edge validation.

### 5.2. Master re-validation

Master repeats all checks available in the synced payload, rejects
edge-originated `escalation_*` fields, and records discrepancies in the audit log.
Re-validation is deterministic and uses no LLM. An invalid edge verdict does not
silently become trusted knowledge or an escalation input.

## 6. Per-mode prompts

Every prompt uses evidence-first output: quote, basis, verdict, confidence level,
then concise reasoning. NEEDS_REVIEW with `low` or `speculative` is an expected
outcome, not a failure. Prompts must not ask for a subjective “high if confident”;
they must enumerate allowed bases and FP-absence rules.

- **SAST:** recognize sanitizers, input validation, fixtures, and dead code;
  require file evidence before any future Mode-B verification.
- **Secrets:** check placeholders, examples, paths, filenames, and test context;
  redact secret excerpts.
- **CVE:** verify component/version and affected range; use reachability only when
  actually established; record CVE source and knowledge cutoff.
- **IaC:** quote the violating block, inspect variables/overrides, and never cite
  a policy absent from input data.

Each mode has its own prompt SHA-256 recorded in `triage_verdicted`. A prompt
change invalidates reuse only for that mode and creates a revision with
`revision_reason=prompt_updated`.

## 7. Master-owned calibration and acceptance criteria

Edge supplies events and per-mode distributions. Master computes metrics using
human-confirmed knowledge and cross-project history:

- accuracy per category and mode;
- reliability by confidence level, separately for zero/nonzero evidence reads;
- false escalation rate, with a stricter limit for critical severity;
- downgrade counts and reasons;
- high-capability violations after validation, which must be zero;
- anchor-bias distribution per mode.

The sample contains the existing 100-finding review bundle plus additional CVE
and IaC examples where coverage is insufficient. Stratify by mode, evidence reads,
and candidate level, including low candidates. Human review is blind: verdict,
confidence level, and basis are assigned before seeing model output.

Failure criteria are fixed before evaluation:

1. Any post-validation high without high-capable basis rejects the validator.
2. High accuracy below 80% in a mode disables escalation for that mode.
3. False escalation above its predefined critical limit disables the threshold.
4. Any `file_verified` without a valid read event is a protocol failure.
5. High above 70% in a mode triggers prompt review for anchor bias. This is not a
   universal rejection threshold: manifest-CVE may legitimately dominate direct
   evidence, so mode-specific expectations are fixed before labeling.

## 8. Modes A/B and prefill

Mode A is the initial cheap configuration:

- SAST: `direct_snippet`;
- Secrets: `direct_snippet_credential`;
- CVE: `manifest_version_match`;
- IaC: `policy_rule_direct`.

It does not require additional file reads and does not increase prefill.

Mode B enables `file_verified` and `reachability_verified` after a separate
experiment. These can add 5–20k tokens per finding and require the complete
read-event linkage. Mode selection and evidence reading belong to edge; master
cannot retroactively create missing edge evidence.

## 9. Relationship to ADR-0017 and failure behavior

TTL reuse, revisions, and provenance remain valid. The new freshness requirement
is the presence of categorical `confidence_level`; prompt hash is also compared.
Revision reasons include `ttl_expired`, `manual`, and `prompt_updated`.

Numeric events remain unchanged in append-only history but are not eligible for
new-protocol reuse. No migration or historical rewrite is performed.

Edge does not wait for master escalation. If master is unavailable, edge still
classifies and journals verdicts with confidence and evidence. Findings retain
scanner severity and escalation is deferred until synchronization. This is
fail-deferred, not fail-closed, and is independent of CI unresolved-finding gate
behavior.

## 10. Implementation order

1. Keep this ADR Proposed.
2. Edge: evidence/provenance fields and downgrade journaling.
3. Edge: deterministic validator, per-mode prompts, prompt hashes, and Mode A.
4. Master: accept new fields, re-validate, add append-only escalation records and
   versioned policy evaluation.
5. Master: blind labeling and calibration using human-confirmed knowledge.
6. Only after calibration: consider enabling severity escalation policy.

## 11. Risks and references

Risks include relabeled anchor bias, formal evidence without read linkage,
prefill growth, CVE presence/reachability confusion, offline credential activity
claims, self-reported deployment status, and costly false critical escalation.
Relevant approaches include stated-confidence protocols, VEX evidence semantics,
self-consistency voting, conformal prediction, production prompt-length traces,
and evidence that additional context can sometimes degrade judgment. These
references motivate validation but do not replace the project’s own labeled
experiment.

## 12. Out of scope

- Enabling severity escalation before calibration.
- Mode-B file/reachability verification.
- Rewriting or migrating historical numeric events.
- Changing TP/FP/NEEDS_REVIEW semantics.
- Mutating source verdict events when master policy changes.
