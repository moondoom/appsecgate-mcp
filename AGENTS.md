# AGENTS.md — AppSecGate MCP

## Project
AppSecGate MCP — local security scanner for AI agents and developers.
Python 3.12+, FastMCP, Pydantic 2.7, SQLite. The server finds, stores, tracks,
and verifies findings. Fix generation is done by the AI agent's own LLM — the
server NEVER does it.

Full architecture: `docs/architecture.md`. Open tasks: `docs/open-tasks.md`.
Read the relevant docs section before any change.

## Project Map
- `mcp-server/src/` — MCP server (tools, hooks, scanners)
- `appsecgate-master/src/` — central master server (Phase 2, ADR-0004/0006):
  events/aggregate/audit, REST API (`api/`), read-only MCP (`mcp/`);
  MS-4 and PostgreSQL backend (DB-1…DB-9, ADR-0012) done
- `appsecgate-agent/src/` — server-agent MVP (AG-5): deterministic MCP stdio
  report mode, no LLM
- `mcp-server/src/appsecgate_mcp/sync/` — edge sync (MS-3/MS-5, ADR-0004 §4.2):
  `appsecgate-mcp sync` on the host (export/outbox/push + pull CI/global
  suppressions + master policy, stdlib urllib). No network calls from the MCP
  server (invariant #2)
- `mcp-server/src/appsecgate_mcp/rules/fetch.py` — host-only
  `appsecgate-mcp rules list/install/remove` (pinned external rules → user
  overlay, explicit language profiles + provenance). External rules are not
  vendored. No network calls from the MCP server (invariant #2)
- `mcp-server/src/appsecgate_mcp/server/` — MCP tools (`scan_file`, `scan_diff`,
  `scan_project`, `get_fix_context`, `get_fix_context_batch`, `verify_fix`,
  `verify_fix_batch`, `query_findings_db`, `export_snapshot`, `get_config`,
  `update_config`, `submit_feedback`, `get_scan_history`, `suppress_finding`,
  `check_gate`, `get_scan_findings`, `read_project_file`; session — `session.py`,
  tool registration — `tools/`, entrypoint — `cli.py`). Public API re-exported
  from `server.py` (facade); imports like `from appsecgate_mcp.server import mcp`
  remain valid
- `mcp-server/src/appsecgate_mcp/scanners/` — Semgrep, Gitleaks, TruffleHog, Trivy
- `mcp-server/src/appsecgate_mcp/storage/` — SQLite schema, views; stores in
  `storage/stores/` (one class per module)
- `mcp-server/tests/` — 535 tests, all green
- `config/default.yaml` — default config
- `docs/` — architecture, ADRs, open tasks, reports

## Glossary
- **Finding** — one scanner finding (rule_id + file + snippet)
- **Fingerprint** — deterministic ID matching findings across scans
- **Suppression** — suppress a finding (local / ci / global)
- **Escalation** — move a finding to the next funnel level
- **shown_findings** — journal of findings shown to the developer locally
- **Context package** — data for the LLM agent, NOT a prompt

## Invariants (violating = error, not warning)
1. Project mounted `:ro` — server NEVER writes project files. Never.
2. `network_mode: none` — no HTTP calls. Not in Phase 1, not "for the future".
3. Zero LLM calls on the server. No `openai`, `anthropic`, `ollama`, `httpx`
   for LLMs. Context package is data, not a prompt.
4. Secret redaction BEFORE DB write. Not "on read" — on write.
5. `query_findings_db` — `SELECT` on public views only. No
   `UPDATE`/`DELETE`/`ATTACH`/`PRAGMA`.
6. `project_id` fixed at `SessionState.initialize()`. Changing `project_path`
   mid-session → error, not warning.

If a task requires violating an invariant — stop and ask.

## Code Conventions
- Python ≥ 3.12, `from __future__ import annotations` in every module.
- Pydantic v2 (`BaseModel`, `Field(default_factory=...)`).
- `ruff`: line-length 100, select E/F/I/W/UP/B.
- `pytest`: `asyncio_mode=auto`.
- Scanners run only via `subprocess`, no shell (`scanners/runner.py`).
- Stores in `storage/stores/` (one class per module); SQLite access only via
  `storage/db.py`.
- All paths in responses and fingerprints are project-relative, forward slashes.
- `update_config` validates first, then atomic-writes (`_atomic_write`), rolls
  back on failure.
- Docs language: `README.md` and `docs/` are English only; Russian only in
  `README.ru.md`.

## Product Principles (unchanged)
- **Warn-only locally.** Block only in CI (Phase 2).
- **Shown journal.** Every shown finding goes to `shown_findings.db`.
- **Offline by default.** `network.mode: offline`, no auto-detect.
- **Scanner isolation.** Each scanner is a separate process, no AGPL imports.
- **No language auto-detect.** Profiles set explicitly in config.

Required deps: `mcp`, `pydantic`, `PyYAML` only; optional extra `agent` —
`openai` per ADR-0014. Other production deps forbidden without explicit
approval. Dev deps (`pytest`, `ruff`) — don't touch without reason.

## Rule: model output is for judgment, not computation

### Principle
Any value the system can compute deterministically MUST be computed by the
system, never requested from the model. The model's job is judgment under
uncertainty (verdict, evidence selection, explanation). The system's job is
anything with a mathematically correct answer (hashing, counting, line
numbers, timestamps, fingerprints, IDs, byte lengths, path normalization).

If a field has a single correct value derivable from inputs, the model must
not be asked to produce it.

### Why (observed three times)
- ADR-0016: salt at end → measured cache-hit, not prefill
- ADR-0017: experiment used a different project_id → measured absence of
  reuse, not reuse
- ADR-0018: prompt asked the model for `quote_hash` (SHA-256); validator
  compared it to the computed hash → 100% of `high` downgraded via
  `quote_mismatch`; measured model arithmetic, not calibration

Each time, the spec asked the model for something deterministic and got a
deterministic failure. Smoke (2/2 cases) confirmed before baseline — desired
detection order.

### Two sub-rules
**1. Deterministic values → system computes, model never sees.**
Examples: `quote_hash`, `fingerprint`, `line_start`/`line_end`, `byte_size`,
`timestamp`, `id`, `path_normalized`, `sha256(...)`, `uuid`, `epoch_ms`. If
the model outputs these, it's a spec bug — remove the field from the model
contract.

**2. Model judgment → system verifies against ground truth.**
The model may produce `verdict`, `confidence_level`, `evidence_basis`,
`evidence_quote`, `reasoning`. Every non-free-text output is deterministically
verified against ground truth before write:
- `evidence_quote` → substring/fuzzy match in `source_file` / snippet
- `evidence_basis` → membership in per-mode high-capable set
- `confidence_level` → consistent with `evidence_basis`
- `verdict` → allowed enum

Verification failure = downgrade or reject, never silent accept.

### Spec-writing checklist (before any baseline run)
For every field in the model output contract:
- [ ] **Deterministic** → remove from model contract; system computes; log
      alongside model output
- [ ] **Judgment** → keep; add deterministic verifier; define
      downgrade/reject action
- [ ] **Mixed** (e.g. "quote + hash") → split: model gives quote, system
      gives hash. Never bundle

Unclassifiable → mixed → split.

### Smoke before baseline
Before any multi-repo baseline run, run a 2–3 case smoke and check:
- [ ] 0% of deterministic fields are model-produced (they should not appear
      in the model contract at all)
- [ ] No `downgrade_reason` dominates at ~100% — if it does, either the
      spec asks for something the model cannot deliver, or the verifier is
      wrong; fix before baseline
- [ ] At least one `high` survives the validator end-to-end

A 100% downgrade rate in smoke is a spec bug, not a model limitation. Do not
spend 10 repos measuring it.

### When in doubt
If the question is "can the model do X?" and X has a correct answer that is
computable, the answer is "don't ask". If X requires judgment, ask, then
verify. There is no third case.

## No migration
Product has not been released. No migrations needed. SQLite schema is created
from scratch in its final form. Non-matching tables are recreated.

## Build / Test / Format
**Always use `make`, not direct utilities.** No manual `docker build -t ...`,
`uv run pytest`, `ruff check .` — only Makefile targets.

| Target | What it does | When |
|--------|--------------|------|
| `make check` | ruff + pytest for all three packages | before every commit |
| `make format` | ruff format (mcp-server) | after changes |
| `make master-format` | ruff format (appsecgate-master) | after changes |
| `make master-test` / `master-lint` | tests / ruff for master | working on master |
| `make agent-test` / `agent-lint` / `agent-format` | agent checks | working on agent |
| `make docker-build` | build `moondoom/appsecgate-mcp:0.1.0` | after commit |
| `make docker-run` | run container with project | debugging |
| `make docker-down` | stop container | after debugging |
| `make experiment-master-up` / `experiment-master-down` | isolated master smoke | before/after agent smoke |
| `make experiment-mock-llm` | deterministic mock for autonomous agent | preliminary runs |
| `make experiment-gate-smoke` | live T-01/T-04/T-07 agent smoke | after agent changes |
| `make experiment-dev-run` | real Q3 on dev corpus | iterative dev versions |
| `make experiment-corpus-prepare` / `experiment-run-config` | 300 repos + frozen config | before main run |
| `make experiment-agent300-preflight` / `experiment-agent300-run` | preflight / main 300 corpus | only after freeze |

Canonical image name: `moondoom/appsecgate-mcp:0.1.0` (set in `Makefile` and
`docker-compose.yml`). Manual `docker build` with the wrong tag is forbidden.

535 mcp-server + 150 appsecgate-master + 8 appsecgate-agent tests must be
green. If a test fails — stop and investigate; NEVER "update the test to
match the code".

## File Size Limits
Controlled by `mcp-server/tests/test_file_size_limits.py` (`make check`):

| Category | Limit | Exceptions |
|----------|-------|-----------|
| Python (`.py`) | ≤ 400 lines **and** ≤ 20 KB | — |
| Documentation (`.md`/`.html`/`.txt`) | ≤ 500 lines **and** ≤ 40 KB | `docs/product-vision.md` (historical artifact), `docs/architecture.md` and `docs/adr/` (living references and ADR specs, do not split) |
| `AGENTS.md` | ≤ 500 lines and ≤ 40 KB | living agent reference, do not split (doc limit since 2026-11-06) |
| Hard ceiling (all text files) | ≤ 1500 lines **and** ≤ 60 KB | — |

Exceeding a limit → **split into modules**, not disable the check. Exceptions
only for files that should not be split (historical artifacts, living
references), with a justification comment in the test.

## Rules
- One PR = one roadmap stage (`docs/open-tasks.md`, `docs/architecture.md` §8)
- Don't change existing MCP tool signatures without explicit instruction
- Don't remove `shown_findings`, `suppressions`, `feedback` tables
- Don't add fields to `Config` without explicit instruction — `update_config`
  validates the schema; an extra field breaks validation

## What NOT to do
- No `subprocess` with `shell=True`
- No writing files > 10 MB to `/tmp` (tmpfs 100M)
- No logging prompts or raw secrets
- No "improving" the DB schema — recreate per `docs/architecture.md` only
- No refactoring that wasn't requested
- No `try/except` around invariants "just in case"

## Workflow: Plan vs Act
- **Plan** — architecture, spec analysis, feature decomposition, complex bug
  debugging (>2 iterations in Act). Does not edit files.
- **Act** — implement the plan step, edits, tests, run commands.
- If a task is "add a tool", "fix a test", "update a field" — Act, no Plan.
- Act-model stuck for 2–3 iterations → switch to Plan.
- Architectural decisions recorded in `docs/adr/`, see `README.md`.

## Definition of Done
Task is complete when:
1. `make check` is green
2. All 693 tests + new ones (if added) pass
3. Changes match one roadmap stage (`docs/open-tasks.md`)
4. No invariant violated
5. No new production deps

Any item missing — task NOT complete.

## Common tasks
- **Add MCP tool** → `mcp-server/src/appsecgate_mcp/server/tools/`
  (`@mcp.tool`), test, README.md update ("MCP tools (17)" section)
- **Add scanner** → `mcp-server/src/scanners/`, wrapper, test with mock
- **Fix test** → first understand WHY it failed. If code is right — update the
  test. If test is right — fix the code. Not the other way around.
- **Update docs** → README.md / `docs/architecture.md` / `docs/open-tasks.md`;
  architectural decisions — `docs/adr/`

## When to stop and ask
- The task requires violating an invariant
- A test fails and it's unclear whether code or test is right
- The task requires a new production dependency
- The task goes beyond one roadmap stage
- It's unclear which docs section the change belongs to
- Open tasks live in `docs/open-tasks.md`, not in AGENTS.md

## Agent File Access (Cline / AI agents)
- Read files ONLY through built-in tools (`read_file`, `list_files`,
  `search_files`)
- Do NOT use `bash`/`execute_command` for `cat`, `ls`, `grep`, `find`, `head`,
  `tail`, `wc`, `sed -n`, `awk`, or `ls foo && echo FOUND || echo NOT_FOUND`
- `execute_command` allowed only for:
  - `make` targets (`make check`, `make format`, `make docker-*`)
  - git operations
  - running tests/linter — but only via `make`
- Working directory IS the project root. Use relative paths, no
  `/home/animage/projects/...` prefix
- To check file existence, use `list_files` or `search_files`, not
  `ls ... || echo`