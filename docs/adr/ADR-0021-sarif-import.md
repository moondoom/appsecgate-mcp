# ADR-0021: SARIF import — external scanner reports into the findings funnel

**Status: DRAFT, pending owner review (2026-11-07). Not committed.**

## 1. Context

AppSecGate stores, tracks, gates, and feeds findings to the triage agent, but
today findings enter only through the four bundled scanners (Semgrep,
Gitleaks, TruffleHog, Trivy). Teams already running other scanners (CodeQL,
SonarQube, Checkmarx, Bandit, Semgrep CE with custom rules, CI-native tools)
must choose between that scanner's silo and AppSecGate's funnel. SARIF 2.1.0
is the de-facto interchange format these tools already emit.

Importing SARIF lets AppSecGate be the single funnel — dedup, shown journal,
gate, guided triage, master knowledge — without replacing anyone's scanner.
It also fits the product principle "scanner isolation": an importer is a
parser, not a scanner process.

SonarQube does not natively export findings to SARIF. Coverage requires an
external export step (`sonar-tools` or equivalent) before
`appsecgate-mcp import`. The import path is identical for any tool that
emits SARIF; the export step is the caller's responsibility. Taint-based
rules (injection) are a commercial SonarQube feature; if an experiment
intends to compare taint-based findings against Semgrep, the comparison is
only reproducible on a licensed SonarQube instance.

## 2. Decision (proposed)

A host-side command, not an MCP tool:

```
appsecgate-mcp import --format sarif --scanner <name> [--category <cat>] report.sarif
```

- Runs on the host against the project's data dir, same trust level as
  `appsecgate-mcp sync` (no new invariant surface; no network, no LLM).
- Imported findings are written to the findings store as a scan of scanner
  `sarif:<name>` and flow through the existing pipeline unchanged:
  fingerprints, dedup, shown journal, gate, guided triage, sync events.
- The importer never invents data. Missing SARIF fields stay absent
  (`rule_hash_status=unavailable` when the rule definition is not in the
  report, null line numbers become file-level findings with line_start=1).

### 2.1. Integration order

- **CI:** `import` runs before `check_gate`, so the gate sees imported
  findings. Recommended order: `import → check_gate → (optional) agent`.
  Imported findings participate in `block_on_unresolved_local` identically
  to native findings.
- **Agent:** `import` runs before `agent --mode=ro`. Imported scan-events
  are included in `get_scan_findings` and in the inventory hash; the guided
  controller processes them like any other finding.

Automation (cron, CI step, watcher) is the caller's responsibility; the
importer is explicit, not a daemon.

## 3. SARIF subset (v1)

From each `run`: `tool.driver.name`/`version`, `rules[]` (id, default
severity, short description as rule doc). From each `result`:
`ruleId`, `level`, `message.text`, `locations[0].physicalLocation`
(`artifactLocation.uri`, `region.startLine/endLine`, `snippet.text`),
`partialFingerprints` (kept as provenance, not used as identity).

Mapping:

| SARIF | AppSecGate |
|---|---|
| `level=error` | high |
| `level=warning` | medium |
| `level=note` | low |
| `level=none` | info |
| rule `defaultConfiguration.level` | fallback when result has no level |
| `--category` flag or per-import config | category (`sast` default) |

Severity mapping table lives in config (`import.severity_map`), validated by
`update_config`; the defaults above are the shipped mapping.

## 4. Identity and dedup

- Fingerprint per ADR-0001: scanner = `sarif:<name>`, rule_id, normalized
  project-relative path, line window. A SARIF result and a Semgrep finding
  for the same code are **different findings** (different scanner identity)
  unless a later semantic-dedup layer (P1/P2) merges them — recorded as
  known duplication, not merged silently.

  **Known duplication until the semantic dedup layer (P1/P2).**
  `partialFingerprints` is preserved as provenance specifically for a future
  cross-scanner merge; it is not used as identity today. Until that layer
  ships, duplicate findings across scanners are expected and must not be
  reported as an import error.
- Re-importing the same file is idempotent: same fingerprints, scan
  reconciliation marks resolved what disappeared.

## 5. Safety and invariants

- Snippets from SARIF pass through the same redactor before DB write
  (invariant #4) — SARIF snippet text may contain credentials.
- Paths are normalized to project-relative forward slashes; results whose
  artifact URI escapes the project root are rejected and counted.
- Partial import is explicit: the command reports `imported / skipped` with
  per-skip reasons (`no_location`, `path_outside_root`, `no_rule`), never
  fails silently on individual results; malformed file → exit 2, no write.
- No network, no LLM, no project writes (invariants #1–#3 untouched).

## 6. Events and provenance

Import produces a scan event with `scanner=sarif:<name>`, SARIF file
SHA-256, tool name/version, and result counts, so master can distinguish
imported findings from live scans and audit re-imports.

## 7. Out of scope (v1)

- SARIF `graph`/`codeFlows`/taint traces, `fixes`, `taxa` (CWE mapping is
  read when trivially present, not required).
- Watching directories / CI webhook ingestion — import is an explicit
  command; automation is the caller's job (cron, CI step).
- SARIF **export** (MS-8 covers DefectDojo; SARIF export is a separate ADR
  if needed).
- SonarQube-native export is not part of this ADR; only SARIF ingestion is
  specified.
- SARIF import is a **host-side command only**. It is not an MCP tool, not a
  PostToolUse hook, and not auto-imported by `scan_project`. Reasons:
  preserves scanner isolation (importer is a parser, not a scanner); keeps
  the CI/agent path single and testable; avoids expanding the MCP
  container's attack surface to arbitrary SARIF files. AI clients that need
  import run `appsecgate-mcp import` via their shell, exactly as they run
  `sync` or `ci`.

## 8. Verification

- Fixture SARIF files (minimal valid, missing locations, path escape,
  secret-in-snippet) under `mcp-server/tests/fixtures/`.
- Tests: mapping table, idempotent re-import, rejection accounting,
  redaction of imported snippets, fingerprint stability across imports.
- Tests assert that `scan_project` and `serve` do not read `.sarif` files
  from the workspace and do not expose an import MCP tool. The only entry
  point is the CLI command.
- E2E: import → `check_gate` → guided triage over imported findings.

### 8.1. Experiment: cross-scanner verdict quality (deferred, separate protocol)

Not part of v1 acceptance. Requires: (a) SARIF export from SonarQube via
`sonar-tools` on a fixed repository snapshot; (b) import into AppSecGate;
(c) guided triage over the union of native and imported findings; (d) a
human-labeled subset for quality comparison.

The pre-registered hypothesis and metrics belong to a separate protocol
(ADR-0022 candidate), not to this ADR. This ADR guarantees only that the
import path is correct and idempotent; it makes no claim about SonarQube
verdict quality.

## 9. Open questions for review

1. Category inference: is a per-import `--category` enough, or do we want a
   per-tool config table (`import.tool_categories`)?
2. Should imported findings be triage-eligible by default, or land in a
   `needs_confirmation` state until a human blesses the source once?
3. ~~Multi-run SARIF files~~ — **resolved in review (2026-11-07):** multi-run
   files are split into one scan per `run`, with
   `scanner=sarif:<name>:<run_index>` (or `<driver.name>` when unique within
   the file). Rejecting multi-run files is not acceptable — it would exclude
   valid SARIF from tools that batch multiple analyzers. Tests cover: two
   runs with different `driver.name`; two runs with the same `driver.name`
   (index disambiguates); one empty run; a run with zero results.
