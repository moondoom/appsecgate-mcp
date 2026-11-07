# ADR-0015: Autonomous triage agent and master knowledge

**Status:** Accepted  
**Date:** 2026-11-04  
**Related:** ADR-0004, ADR-0006, ADR-0009, ADR-0012, ADR-0013, ADR-0014

## 1. Context

The original RO-agent read only the severity-ranked top 10 findings and classified each finding from a prebuilt context in one LLM request. This limited investigation, made the funnel incorrect, and did not exercise an autonomous agent.

The replacement is a single autonomous RO-agent whose task is to classify every current finding as TP, FP, or NEEDS_REVIEW. No fixed/free switch or legacy agent mode is preserved.

Master already stores findings and lifecycle events. It also needs versioned model/human verdicts, sanitized cross-project knowledge, and a central CVE reference. ADR-0013 provides the read-only SQL MCP pattern used to access these data.

## 2. Decision

Implement:

1. an autonomous LLM tool-calling loop with a deterministic controller;
2. bounded, redacted reads of additional project files;
3. an append-only local verdict journal synchronized through the existing edge outbox;
4. project-scoped verdict history and a sanitized cross-project knowledge view;
5. central CVE/GHSA records and affected package ranges;
6. read-only access through master MCP `describe_schema` and `query_findings_db`.

```text
scanner MCP (stdio, no network)
  → full current inventory → autonomous LLM agent
       ├─ read_project_file / get_fix_context
       ├─ master MCP: similar verdicts + CVE (read-only)
       └─ submit_verdicts
  → controller: pending / loop detection / restart / compaction
  → local triage journal → edge sync → master events
```

Scanner MCP remains network-isolated. The agent, not scanner MCP, connects to the LLM and master MCP. Master MCP never writes data.

## 3. Full inventory and funnel

`scan_project.top_findings` remains a UX summary and is not the triage boundary. `get_scan_findings` exposes the exact latest scan result in deterministic pages with the full ID list and inventory hash.

`ScanMeta` separately records `scanner_raw`, `in_scope`, `dedup_level1`, `dedup_level2`, `suppressed`, and `eligible`. These values are read from structured report fields, never reconstructed from log text.

Every eligible finding must finish in one of these states: accepted model verdict, explicit missing/degraded result, or infrastructure failure. Missing findings are not silently converted into NEEDS_REVIEW.

## 4. Controller

The agent supports two loop modes selected by `agent_mode` (`--agent-mode`, default `guided`). The scan always runs before the LLM starts; neither mode exposes scan tools to the model.

In `free` mode the model drives the full tool set described below.

In `guided` mode the harness drives a deterministic loop: it pages the inventory, pre-fetches `get_fix_context_batch` and dependency manifests for each batch, and sends one self-contained request per batch. Batch size derives from the model output budget (`llm_max_tokens`), not from a specific model. Truncated or unparseable batches are split in half and retried; a finding that still fails stays explicitly pending (`guided_incomplete`, `failed_findings`) and is never silently converted into NEEDS_REVIEW. Content-JSON verdicts are accepted as a fallback for models without reliable tool calling.

**Important (2026-11-05):** guided is still an agentic mode, not one-shot labeling. Within a batch the model may gather missing evidence through `read_project_file` and master knowledge tools before its single `submit_verdicts` call, bounded by `_MAX_BATCH_ITERATIONS = 4`. Verdicts are never revised after acceptance within a run. A later run may create an append-only revision with `supersedes_verdict_id`. Absence of a package or pattern in a snippet is not evidence of absence: FALSE_POSITIVE on incomplete evidence is prohibited by the prompt.

**Update (2026-11-07, GD-13):** measured master-tool usage in guided was zero across 40 runs (`artifacts/master-tools-usage.json`), so master knowledge tools are removed from the guided tool list and `read_project_file` is gated behind `APPSECGATE_MODE_B=1`. Reuse (GD-10) still reads master knowledge harness-side before batching; only model-visible master tools are removed. Free mode retains the full tool set.

**Reuse validation (2026-11-06):** controlled rev1v3 runs validated fresh reuse and append-only revisions; see ADR-0017. Numeric confidence is the legacy protocol. ADR-0018 proposes categorical evidence-based confidence for new events, per-mode prompt-hash invalidation, and master-owned severity escalation. Historical numeric events remain unchanged but are excluded from the new protocol.

**Guided-redesign addendum (2026-11-07, implemented; adoption pending acceptance):** after the retry/split policy is exhausted, context overflow, call timeout, post-retry LLM call errors, and per-finding budget exhaustion no longer leave a finding indefinitely pending. They produce terminal `NEEDS_REVIEW` with `failure_reason=context_overflow|timeout|llm_error|budget_exhausted` and `failure_detail`, distinguishing model-judged review from model failure. Such terminal events count toward coverage but not `failed_findings`; missing findings and unhandled infrastructure failures remain pending/failed. This is a deliberate change to the paragraph above, not a silent relaxation of “missing findings are not converted into NEEDS_REVIEW”: only a measured model failure after retries qualifies. Acceptance uses a provisional 600 s call timeout; a smaller value requires calibration at the actual four-slot operating point. LLM call failures are batch-fatal before the terminal verdict is emitted (GD-9). Implementation and gates: ADR-0019; timeout/overflow evidence: ADR-0016 §12 and §14.

**Resume and partial-failure exits (2026-11-07, GD-14/GD-15):** because the journal is append-only and durable per run id, a restarted run restores already-accepted verdicts from `triage_verdicts.ndjson` without LLM calls (`agent/resume.py`, opt-out `APPSECGATE_AGENT_RESUME_JOURNAL=0`); rows outside the current inventory are skipped. Token-budget exhaustion with pending findings is no longer run-fatal: the report is emitted with `exit_reason=budget_partial`, and a sync failure is reported as `exit_reason=sync_error` with the triage report still delivered. One transient transport retry (5xx/connection reset) is allowed per call; timeouts and invalid outputs are never retried (GD-9 unchanged).

## 4. Controller

The controller does not make security decisions. It owns:

- full inventory, pending IDs, accepted verdicts, and evidence;
- reminders about concrete pending IDs after premature termination;
- verdict ID/schema validation and duplicate detection;
- repeated-call and no-progress loop detection;
- diagnostic hints followed by restart from the latest checkpoint;
- idempotent verdict preservation across restarts;
- bounded tool results and deterministic context compaction;
- pending/verdict/evidence/budget preservation during compaction;
- iteration, token, time, restart, and compaction limits and their metrics.

A loop or exhausted budget produces an explicit degradation. It is not a successful model verdict.

## 5. File access

`read_project_file` accepts a relative path and bounded line range. It rejects traversal, symlink escape, binary or oversized files, and known secret files. Returned content is redacted before reaching the LLM. Logs contain only path, range, size, and status, never file contents.

## 6. Verdict journal and events

Each accepted verdict is redacted before it is appended to `triage_verdicts.ndjson` in the agent data directory. Duplicate model verdicts are not appended during retries or restarts.

The existing sync pipeline appends these records to the durable outbox and pushes them to `/v1/events` as typed `triage_verdicted` events.

The event contains:

- `verdict_id`, optional `supersedes_verdict_id`, `fp`, and `run_id`;
- `verdict`, optional integer `confidence`, `verdict_source=model|human`, and `review_status`;
- `revision_reason` and optional `actor_id` for retrospective history;
- scanner/rule IDs, overall `ruleset_hash`, and per-rule `rule_hash` with explicit
  `definition_sha256|unavailable` status;
- optional rule/package/ecosystem/CVE correlation keys;
- redacted explanation and structured evidence;
- agent/model/prompt/tool versions and timestamps.

`client_event_id` is deterministic by `verdict_id`, making sync idempotent. A correction references a superseded event instead of rewriting history. Human and model verdicts are separate events; later human review never erases a model mistake.

## 7. Knowledge views

`v_triage_verdicts` contains full project-scoped model and human history. PostgreSQL uses RLS and `security_invoker`.

`v_triage_knowledge` contains only human-confirmed, redacted records. It excludes project keys, run IDs, repository URLs, raw paths, raw code, and secrets. It exposes only generalized correlation keys, verdict, sanitized rationale/evidence, and versions. Unreviewed model answers never enter this view. The view intentionally allows cross-project reads of this sanitized dataset.

`v_cve` and `v_cve_affected` expose global reference data without tenant information. CVE records include source, fetch time, and content hash.

Similarity is deterministic in this stage: exact fingerprint/logical ID, rule and normalized finding kind, CVE/package/ecosystem, then scanner/category/CWE. Historical verdicts are evidence, not authoritative answers. Embeddings are out of scope.

**Guided access amendment (2026-11-07, GD-13, data-gated):** direct guided access to `describe_schema` and `query_findings_db` will be removed only after `artifacts/master-tools-usage.json` demonstrates near-zero usage and no verdict dependency. Guided would then consume these views through deterministic pre-fetch (ADR-0019 Part 6); free mode retains direct read-only tools. Until that measurement and implementation, the current tool behavior remains unchanged.

## 8. CVE ingestion

`cve_records` and `cve_affected_ranges` are separate from append-only finding events. An administrative ingestion job or CLI imports OSV/NVD data, validates the schema, and stores provenance and content hashes. Scanner and LLM do not call external CVE APIs.

Measured runs freeze the CVE snapshot and `knowledge_cutoff`. Queries after the cutoff, current-run verdicts, and parallel-run verdicts are not visible to the agent. Repeated runs use the same cutoff.

If master is unavailable, the agent continues with local scanner facts and records `master_knowledge_unavailable`. It must not invent history or CVE details.

## 9. Security

- Project files remain read-only and scanner MCP has no network access.
- Redaction happens before local journal and master event writes.
- Master MCP is read-only with Bearer authentication, RLS, timeouts, row limits, rate limits, and SQL audit.
- Cross-project knowledge contains only sanitized human-confirmed records.
- Files, findings, history, and CVE text are untrusted data, never instructions.
- PostgreSQL knowledge queries execute in a read-only transaction; SQLite queries use a read-only connection and authorizer.

## 10. Observability

Reports preserve pending/missing IDs, tool calls, loops, hints, restarts, compactions, checkpoints, token usage, latency, master failures, inventory hash, knowledge cutoff, and CVE snapshot. Process completion and triage completeness are separate metrics. Exceeding the LLM token budget is an infrastructure error only while findings remain pending; a fully triaged run instead completes with an explicit budget warning.

## 11. Implementation map

- `mcp-server/src/appsecgate_mcp/agent/`: autonomous loop, controller, master client, and journal;
- `mcp-server/src/appsecgate_mcp/server/tools/`: full inventory and safe file reader;
- `mcp-server/src/appsecgate_mcp/sync/`: verdict journal export through the outbox;
- `appsecgate-master/contracts/`: typed triage event;
- `appsecgate-master/storage/`: verdict knowledge, CVE stores, and read-only queries;
- `appsecgate-master/mcp/`: streamable HTTP MCP implementation from ADR-0013;
- `experiments/tp-0001/`: non-destructive `asgfree` collection and blind-review artifacts.

The old one-shot agent pipeline is replaced rather than preserved. Existing scanner MCP contracts remain compatible except for additive read-only tools and structured scan metadata.

## 12. Verification

- All assigned findings have a verdict or explicit missing/degraded state.
- Pending reminders, loop restarts, compaction, and journal idempotency are tested.
- File isolation and redaction are tested.
- Project RLS, global knowledge sanitization, cutoff, and read-only SQL are tested.
- CVE hit/miss, snapshot versioning, and master-unavailable behavior are tested.
- Master MCP auth, schema, query, and project isolation pass ASGI E2E tests.
- `make check` passes before iterative development runs and before the frozen main corpus.
