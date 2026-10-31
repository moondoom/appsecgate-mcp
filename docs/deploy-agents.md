# Deploying AppSecGate MCP for AI Agents

Guide for connecting the MCP server to AI coding agents (task T2,
`docs/open-tasks.md`). Configuration examples are provided in this document;
copy them into your client's config directory. A local Continue config
(`.continue/mcpServers/appsecgate.yaml`) may be kept under `.gitignore` —
Continue remains a supported client, but is not used in development.

## 1. Canonical server name

The MCP server name determines the tool prefix visible in the client:

```
mcp__<server_name>__<tool_name>
```

The canonical name is **`appsecgate`** (no spaces). Example prefixes:

- `mcp__appsecgate__scan_file`
- `mcp__appsecgate__scan_project`
- `mcp__appsecgate__get_fix_context`
- …and so on for all tools.

Spaces and uppercase break the prefix in some clients. All documentation
and configs therefore use `appsecgate` verbatim.

## 2. Prerequisites

- Docker image built: `make docker-build` (from repo root).
  Published image: `moondoom/appsecgate-mcp:0.1.0`.
- The project being scanned is mounted `:ro` in the container.
- Network is disabled (`--network=none`) — scanner rules ship locally
  (Rules Bundle), the server is fully offline.
- For local (Docker-free) development: `uv run appsecgate-mcp`.

### Project identity (T9)

`project_id` is stable across sessions and environments:

- if the project is a git repository, the identity is derived from its name
  (`origin` URL, or the directory name) — no configuration needed, works with
  the `.:/workspace:ro` mount;
- to override it explicitly, pass `--project-alias <name>` (or
  `--project-id <id>`); the same flags are available as
  `APPSECGATE_PROJECT_ALIAS` / `APPSECGATE_PROJECT_ID` env vars.

## 3. Common config block

All client examples share the same Docker command. **Optionally** add
`--project-alias <repo-name>` so that different host repositories mapped to
`/workspace` keep independent `project_id` values even when they share the
`appsecgate-data` volume:

```yaml
# Shared block (identical for every client)
type: stdio
command: docker
args:
  - run
  - --rm
  - -i
  - --network=none
  - --read-only
  - --tmpfs=/tmp:size=100M,mode=1777
  - --cap-drop=ALL
  - --security-opt=no-new-privileges:true
  - -v
  - .:/workspace:ro
  - -v
  - appsecgate-cache:/home/appsecgate/.cache
  - -v
  - appsecgate-data:/home/appsecgate/.appsecgate-mcp
  - moondoom/appsecgate-mcp:0.1.0
  - --transport
  - stdio
  - --project
  - /workspace
```

Local (Docker-free) variant for development:

```yaml
type: stdio
command: uv
args:
  - run
  - --directory
  - /absolute/path/to/mcp-server
  - appsecgate-mcp
  - --transport
  - stdio
  - --project
  - /path/to/project
```

> **Caution:** local launch provides **no** isolation (read-only, tmpfs,
> network none). Always use the Docker image for actual use.

## 4. Clients

### Continue

Create `<project>/.continue/mcpServers/appsecgate.yaml`
(or `~/.continue/mcpServers/`) with the following content:

```yaml
name: appsecgate
version: 0.1.0
schema: v1
mcpServers:
  - name: appsecgate
    type: stdio
    command: docker
    args:
      - run
      - --rm
      - -i
      - --network=none
      - --read-only
      - --tmpfs=/tmp:size=100M,mode=1777
      - --cap-drop=ALL
      - --security-opt=no-new-privileges:true
      - -v
      - .:/workspace:ro
      - -v
      - appsecgate-cache:/home/appsecgate/.cache
      - -v
      - appsecgate-data:/home/appsecgate/.appsecgate-mcp
      - moondoom/appsecgate-mcp:0.1.0
      - --transport
      - stdio
      - --project
      - /workspace
    connectionTimeout: 600000
    requestOptions:
      timeout: 600000
```

### Claude Code

Project config file: `<project>/.mcp.json` (or via
`claude mcp add appsecgate -- docker run …`):

```json
{
  "mcpServers": {
    "appsecgate": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i", "--network=none", "--read-only",
        "--tmpfs=/tmp:size=100M,mode=1777", "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "-v", ".:/workspace:ro",
        "-v", "appsecgate-cache:/home/appsecgate/.cache",
        "-v", "appsecgate-data:/home/appsecgate/.appsecgate-mcp",
        "moondoom/appsecgate-mcp:0.1.0",
        "--transport", "stdio", "--project", "/workspace"
      ]
    }
  }
}
```

### Cline

Cline (v4.x) reads MCP servers from its **global** config file
`~/.cline/data/settings/cline_mcp_settings.json` — a single file for the CLI,
desktop and VS Code extension. Legacy paths `.cline/mcp_settings.json` and
root-level `mcp_settings.json` are **no longer read**.

Add the `appsecgate` server to `~/.cline/data/settings/cline_mcp_settings.json`:

```json
{
  "mcpServers": {
    "appsecgate": {
      "type": "stdio",
      "command": "docker",
      "args": [
        "run", "--rm", "-i", "--network=none", "--read-only",
        "--tmpfs=/tmp:size=100M,mode=1777", "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "-v", "/absolute/path/to/project:/workspace:ro",
        "-v", "appsecgate-cache:/home/appsecgate/.cache",
        "-v", "appsecgate-data:/home/appsecgate/.appsecgate-mcp",
        "moondoom/appsecgate-mcp:0.1.0",
        "--transport", "stdio", "--project", "/workspace"
      ],
      "cwd": "/absolute/path/to/project",
      "env": {},
      "disabled": false,
      "timeout": 600
    }
  }
}
```

Important:

- In the global config, use **absolute paths** for `-v` and `cwd` so the
  bind-mount does not depend on which workspace is open. Relative
  `.:/workspace:ro` only works for per-project `.mcp.json` (see below).
- `timeout` in Cline is specified in seconds (600 = 10 min).
- After editing, restart Cline (or reload the VS Code window) —
  the extension will re-read the config.
- On first connect, Cline may ask for a security confirmation —
  approve the `appsecgate` server.

Alternative (project-scoped): a project-level `.mcp.json` in the workspace root.
Cline reads it and shows servers in a separate MCP tab — each server must be
approved once in the UI. Claude Code uses the same file, so one `.mcp.json`
can serve both clients.

### Cursor

File: `<project>/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "appsecgate": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i", "--network=none", "--read-only",
        "--tmpfs=/tmp:size=100M,mode=1777", "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "-v", ".:/workspace:ro",
        "-v", "appsecgate-cache:/home/appsecgate/.cache",
        "-v", "appsecgate-data:/home/appsecgate/.appsecgate-mcp",
        "moondoom/appsecgate-mcp:0.1.0",
        "--transport", "stdio", "--project", "/workspace"
      ]
    }
  }
}
```

## 5. Finding field dictionary

The server returns findings in a machine-readable format; the agent
should present the "issue name" using `rule_id` + `message`.

| Field | Description | Example |
|---------------|---------|--------|
| `finding_id` | finding identifier for `get_fix_context`/`verify_fix`; **equals `fingerprint`** | `9f3a2c88d1b0e4aa` |
| `rule_id` | scanner rule name — the "issue name" (nomenclature varies per scanner) | `aws-access-token` |
| `rule` | short human-readable rule name (last segment of `rule_id`, T15); present in scan summaries alongside the full `rule_id` | `aws-access-token` |
| `message` | human-readable description from the scanner | `AWS Access Key detected` |
| `severity` | `critical` / `high` / `medium` / `low` / `info` | `high` |
| `category` | `sast` / `secret` / `sca` / `iac` | `secret` |
| `scanner` | which scanner found it: `semgrep` / `gitleaks` / `trufflehog` / `trivy` | `gitleaks` |
| `file_path` | relative path from project root | `src/secrets.py` |
| `line_start` / `line_end` | line range | `12` / `12` |
| `snippet` | code fragment (redacted for secrets) | `aws_key = "AKIA…"` |

Agent recommendation: in summary responses, refer to the issue as
`rule_id` (+ `message` in parentheses), for example:
`aws-access-token` (AWS Access Key detected) in `src/secrets.py:12`.

## 6. Post-installation verification steps

1. Restart the client and open the MCP tool list.
2. Verify that tools with the `mcp__appsecgate__` prefix are visible
   (e.g. `mcp__appsecgate__scan_file`, `mcp__appsecgate__scan_project`).
3. Run `scan_file` on a test file in the project
   (e.g. `mcp-server/tests/fixtures/vuln-project/secrets.py`).
4. Expected response: `meta.scanners_ran` is non-empty, `findings` is a list
   of findings; `meta.errors` is empty.
5. `query_findings_db` for `project_id` — records appear after scan
   (`shown_findings`).
6. `update_config` on a `:ro` mount returns `status: readonly` with a
   recommendation — this is **not an error**. The change is not applied;
   settings can be changed by the user (edit `.appsecgate-mcp/config.yaml` in
   the host project or set `APPSECGATE_*` env vars).

## 7. Troubleshooting

| Symptom | Cause | Action |
|---------|---------|----------|
| Client: "failed to start" / empty response | Image not built or image name mismatch | `make docker-build`; verify the tag in config |
| Tools visible but response is a network error | Project cache in `/tmp` is too large (>100M) or bind-mount permission denied | Check tmpfs size and directory permissions |
| Tools NOT visible | Wrong server name / prefix | Name must be `appsecgate` (no spaces); prefix `mcp__appsecgate__` |
| Tools NOT visible (Cline) | Server not in `~/.cline/data/settings/cline_mcp_settings.json` (legacy path `.cline/mcp_settings.json` is not read) | Add the server to the global file and restart Cline/VS Code |
| `scan_file` returned empty `findings` | Rules did not resolve (offline, Rules Bundle empty) | Check `meta.warnings` and `ruleset_hash`; verify the bundle is in the image |
| `meta.errors` is non-empty | Scanner binary unavailable (semgrep/gitleaks/trivy) | Check the image: `docker run --rm moondoom/appsecgate-mcp semgrep --version` |
| `project_id mismatch` error | `project_path` changed within the same session | New project = new session (invariant #6) |

## 8. CI gate (Phase 2, ADR-0003)

The same image runs as a CI gate. It scans the PR diff against the base branch
and fails the build on blockable findings (severity or "shown locally and not
fixed"). Exit codes: `0` pass, `1` blocked, `2` infrastructure error.

```bash
docker run --rm --network=none --read-only \
  --tmpfs=/tmp:size=100M,mode=1777 \
  --cap-drop=ALL --security-opt=no-new-privileges:true \
  -v "$PWD":/workspace:ro \
  moondoom/appsecgate-mcp:0.1.0 \
  ci --project /workspace --base-ref "origin/main" --format text
```

Options: `--base-ref` (default: `gates.ci.diff_base_ref`, i.e. `origin/main`),
`--shown-snapshot PATH` (default `<project>/.appsecgate-mcp/shown.ndjson`),
`--require-shown-snapshot` (fail-closed when the snapshot is missing),
`--format text|ndjson`. Ready-to-use workflow:
`.github/workflows/appsecgate-ci.yml`.

### Shown snapshot (written by the agent, not the server)

For the `unresolved_local` gate the agent maintains
`.appsecgate-mcp/shown.ndjson` in the project (invariant #1: the server never
writes project files). One redacted record per shown finding:

```json
{"fp":"0691d13f93462eba","rule_id":"gitleaks.github-pat","file":"src/main.py",
 "line":42,"severity":"high","shown_at":"2026-10-30T12:00:00Z",
 "verified_status":null,"suppression_scope":null}
```

- Collect data via `query_findings_db` (SELECT `v_findings`) + `get_scan_history`
  (verification attempts, suppressions); `verified_status` ∈ `fixed`/`not_fixed`/
  `wont_fix`, `suppression_scope` ∈ `local`/`ci`/`global`.
- Append-only: never remove previously shown fingerprints; commit the file so
  CI can read it. Missing snapshot degrades to severity-gate with a warning.


## 9. Sync to master (Phase 2, MS-3–MS-5)

The master server keeps a single source of truth for findings across machines
and CI (ADR-0004). The MCP server itself stays offline (invariant #2:
`network_mode: none`) — the **edge** process synchronizes local state from the host:

```bash
appsecgate-mcp sync \
  --data-dir "$HOME/.appsecgate-mcp" \
  --project-id "your-project-id" \
  --master-url https://appsecgate.example.com \
  --api-key "$APPSECGATE_MASTER_API_KEY"
```

What happens:

1. **Export** — reads `shown_findings.db` (local materialized state) and
   reconstructs lifecycle events (`discovered`, `reaffirmed`, `verify_fixed`,
   `suppressed`, …) per the ADR-0006 matrix. `client_event_id` is a
   deterministic UUID, so re-running produces the same events → idempotent.
2. **Outbox** — events are appended to `~/.appsecgate/sync/outbox.ndjson`
   (durable NDJSON queue, dedup by `client_event_id`). Push is filtered by
   project, so another project's events remain queued for their own API key.
3. **Push** — the queue is POSTed to `{master}/v1/events` (stdlib `urllib`,
   `Authorization: Bearer`). 2xx → removed from the queue; 4xx → quarantined
   to `outbox.ndjson.rejected`; 5xx/network → kept for the next run.
4. **Pull** — CI/global suppressions and the central policy are downloaded to
   the same data-dir. Remote suppressions live separately in
   `remote_suppressions` and apply on the next scan without overwriting local
   suppressions. Policy is stored in `master-policies/<project_id>.json` and
   applies to a new/restarted MCP session with precedence
   `default < project < master < env`.

`--project-id` may be omitted when the database contains exactly one project;
it is required for a multi-project database. For Docker, `--data-dir` must
point to the host location of the same data volume read by the MCP container.
Pull failure keeps the last downloaded state for offline use.

Options: `--batch-size`, `--timeout`, `--dry-run` (local export only: no HTTP,
outbox or pulled-file writes; `--format ndjson` for machine output). Exit codes:
`0` ok, `1` push or pull partially failed (retry next run), `2`
infrastructure/configuration error.

Env overrides: `APPSECGATE_MASTER_URL`, `APPSECGATE_MASTER_API_KEY`,
`APPSECGATE_SYNC_OUTBOX`, `APPSECGATE_DATA_DIR`. REST API is implemented in
MS-4; push/pull edge contract follows ADR-0004 §5.2.

| `update_config` returns `status: readonly` | Project is mounted `:ro` (canonical Docker) — not an error | The change is not applied. Ask the user to edit `.appsecgate-mcp/config.yaml` on the host, mount the project `rw` for local dev, or set `APPSECGATE_*` env vars |