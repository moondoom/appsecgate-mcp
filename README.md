# AppSecGate MCP

[![Release](https://img.shields.io/github/v/release/moondoom/appsecgate-mcp?label=release)](https://github.com/moondoom/appsecgate-mcp/releases)
[![Docker Pulls](https://img.shields.io/docker/pulls/moondoom/appsecgate-mcp)](https://hub.docker.com/r/moondoom/appsecgate-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Local-first security scanning for AI coding agents.**

AI agents ship code faster than security can review it. AppSecGate is an MCP
server that scans files, diffs, and whole projects **right inside Claude Code,
Cursor, Cline, or Continue** — offline, without sending your code anywhere.
Findings are normalized, deduplicated by fingerprint, tracked between scans, and
returned to the agent as fix contexts.

> Security should not be a drag. It should be invisible to the developer and
> transparent to security.

**Read:** [Making AI agents paranoid: will MCP replace AppSec? (Habr, RU)](https://habr.com/ru/articles/1099840/)

## When to use / When NOT to use

**Use it when:**

- You build with an AI agent and want every diff scanned before it lands.
- You want findings tracked across scans (deduplicated by fingerprint), not a pile of reports.
- You want to stay offline: no network calls, no code leaves your machine, and the server itself never calls an LLM.
- You want your agent to see the context needed to fix a finding (`get_fix_context`) and to verify the fix later (`verify_fix`).

**Do NOT use it when:**

- You need large-scale GUI triage, RBAC, team dashboards, or ASOC sync.
  Local scanning, centralized policy, and classic CI blocking are already
  implemented; dashboards and ASOC integration are not.

## Demo

<!-- Demo GIF (install + Juice Shop scan): docs/assets/demo.gif — to be recorded. -->

## Quick Install

The server runs as a Docker container. Your project is mounted **read-only**
(`:ro`), the container has **no network access** (`--network=none`), and scans
never write to your source tree.

```bash
docker pull moondoom/appsecgate-mcp:0.1.0
```

### Claude Code

Add to `<project>/.mcp.json`:

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

Or register it directly:

```bash
claude mcp add appsecgate -- docker run --rm -i --network=none --read-only \
  --tmpfs=/tmp:size=100M,mode=1777 --cap-drop=ALL \
  --security-opt=no-new-privileges:true \
  -v .:/workspace:ro \
  -v appsecgate-cache:/home/appsecgate/.cache \
  -v appsecgate-data:/home/appsecgate/.appsecgate-mcp \
  moondoom/appsecgate-mcp:0.1.0 --transport stdio --project /workspace
```

### Cursor

Add to `<project>/.cursor/mcp.json`:

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

Cline (v4.x) reads MCP servers from the shared settings file
`~/.cline/data/settings/cline_mcp_settings.json`. Add the `appsecgate` server:

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
        "-v", "/absolute/path/to/your/project:/workspace:ro",
        "-v", "appsecgate-cache:/home/appsecgate/.cache",
        "-v", "appsecgate-data:/home/appsecgate/.appsecgate-mcp",
        "moondoom/appsecgate-mcp:0.1.0",
        "--transport", "stdio", "--project", "/workspace"
      ],
      "cwd": "/absolute/path/to/your/project",
      "env": {},
      "disabled": false,
      "timeout": 600
    }
  }
}
```

For a shared (user-level) config use an **absolute** project path in `-v` and
`cwd`; a relative `.:/workspace:ro` works only in a per-project `.mcp.json`.

### Continue

Add to `<project>/.continue/mcpServers/appsecgate.yaml`:

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

**Verify the install:** restart the client, then run `scan_file` on any file; tools
appear with the `mcp__appsecgate__` prefix. Full instructions, edge cases, and
diagnostics: [docs/deploy-agents.md](docs/deploy-agents.md).

## Agent mode (coming in 0.1.8)

The read-only agent autonomously triages the complete current inventory instead of
only the top 10 findings. It chooses scanner context, bounded file reads, historical
human-confirmed verdicts, and CVE data through tools. A deterministic controller
tracks pending IDs, detects loops, restarts from checkpoints, compacts context, and
preserves a redacted verdict journal. Synchronization uses the existing edge outbox;
master MCP is read-only. The agent never modifies the project or applies patches.

The LLM runs outside the MCP server and is configured through an
OpenAI-compatible endpoint; the server's no-LLM invariant is unchanged.

```bash
appsecgate-mcp agent \
  --mode=ro --scan=full --policy=warn --output-format=markdown \
  --project . \
  --llm-url http://<llm-host>/v1 --llm-model <model>
```

See the [TP-0001 experiment report](experiments/tp-0001/REPORT.md) for model
benchmarks and aggregate results from 100 repositories.

## MCP tools (17)

| Tool | What it does |
|------|--------------|
| `scan_file` | Scan a single file and return normalized findings. |
| `scan_diff` | Scan staged + unstaged + untracked changes in the current git repository. |
| `scan_project` | Scan the entire project (no arguments) — reconciliation report: counts + TOP-10 + requires_confirmation. |
| `get_scan_findings` | Return a deterministic page of findings from the latest scan, including the full inventory hash. |
| `read_project_file` | Read a bounded, redacted line range from a file inside the project. |
| `check_gate` | Evaluate the latest scan under an advisory policy and return a GateSummary with a recommended action. |
| `get_fix_context` | Return the ContextPack for a finding (finding + code window + rule doc). |
| `get_fix_context_batch` | Return ContextPacks for multiple findings (limit 20). |
| `verify_fix` | Verify a single finding: rescan the file and match by (logical_id). |
| `verify_fix_batch` | Verify up to 20 findings; each file is rescanned once. |
| `query_findings_db` | Read-only SELECT on public views (v_findings, v_summary, v_projects). |
| `export_snapshot` | Export a snapshot of findings in ndjson format (parquet — Phase 2). |
| `get_config` | Return the active (merged) session configuration. |
| `update_config` | Deep-merge updates into .appsecgate-mcp/config.yaml and reload the session. |
| `submit_feedback` | Submit feedback on a finding (FALSE_POSITIVE / CONFIRMED / WONT_FIX). |
| `get_scan_history` | Return the shown findings log (shown_findings.db) with verification attempts. |
| `suppress_finding` | Create or remove a local suppression (`action: suppress\|unsuppress`; does not affect CI gate in Phase 1). |

## Scanners (Phase 1)

| Category | Scanners | Notes |
|----------|----------|-------|
| SAST | Semgrep | Bundled offline rules (Rules Bundle) — no registry access needed |
| Secrets | Gitleaks, TruffleHog | Values redacted before they are stored |
| SCA | Trivy | Vulnerability DB seeded at image build time |

Every scanner runs as a separate subprocess (no shell). Planned for later phases:
Bandit, ESLint (SAST); OSV-Scanner, Dependency-Track (SCA); Checkov, KICS (IaC);
OWASP ZAP (DAST).

## Security model

- **Read-only project.** The project is mounted `:ro`; the server never writes to source files.
- **Offline by default.** `network_mode: none` — no outbound network calls, ever.
- **No LLM calls.** The fix is generated by your agent's own model; the server only ships context data, never prompts.
- **Secrets redacted before storage.** At write time, not at read time.
- **Hardened container.** Non-root UID 1000, read-only rootfs, `cap-drop=ALL`, `no-new-privileges`.

## Configuration

Per-project settings live in `.appsecgate-mcp/config.yaml` and are deep-merged over
the image defaults (`/etc/appsecgate/default.yaml`):

```yaml
version: 1
stack:
  languages: [python, typescript]
  frameworks: [fastapi, react]

scanners:
  sast:
    enabled: true
    tool: semgrep
    rulesets: []          # semgrep rules come from the local Rules Bundle
  secrets:
    enabled: true
    tool: gitleaks
  sca:
    enabled: true
    tool: trivy
    severity_threshold: HIGH

gates:
  local:
    warn_on: [CRITICAL, HIGH, MEDIUM]
    block_on: []            # never block locally
  ci:
    block_on: [CRITICAL, HIGH]
    warn_on: [MEDIUM]
    block_on_unresolved_local: true   # "seen but not fixed" (Phase 2)
    diff_base_ref: origin/main        # base for `appsecgate ci`
```

### Optional: user-downloaded Semgrep rules

The image ships only rules that AppSecGate may redistribute. You can download
additional rules yourself; they are stored in the user data directory, not in
the project, image, or bundled rules. List the pinned sources and licenses:

```bash
appsecgate-mcp rules list
appsecgate-mcp rules install \
  --source semgrep --source trailofbits --profile agent300 --accept-licenses
```

For a custom selection, replace `--profile agent300` with, for example,
`--languages python,javascript,go`. The `agent300` profile keeps Python,
JavaScript, TypeScript, Go, Java, Ruby, PHP, and configuration/IaC rules while
excluding unrelated languages and test fixtures. Downloading happens only in
this host command; MCP scanning remains offline. No image rebuild is needed.

Set `APPSECGATE_RULES_DISTRIBUTION_MODE=commercial` on the MCP container and
mount the same `~/.appsecgate-mcp` host directory at
`/home/appsecgate/.appsecgate-mcp`. With a named `appsecgate-data` volume, run
the install command in a separate networked container using that volume. The
`commercial` setting means that you accept responsibility for the selected
licenses; it is not an AppSecGate commercial license. In particular, Semgrep
rules are for internal use and must not be redistributed.

Review `rules/.external-rules.json` for revisions, hashes, selected files, and
duplicates. Remove a source with `appsecgate-mcp rules remove --source semgrep`.
A changed ruleset also changes scan results and `ruleset_hash`.

### Optional: centralized CI and master sync

Local MCP scanning stays offline and warn-only. For shared findings, policy
synchronization, and blocking CI scans, use the separate master + edge setup
described in [docs/deploy-master.md](docs/deploy-master.md).

## Build from source

```bash
make setup          # create the uv environment
make check          # lint (ruff) + tests (pytest)
make docker-build   # build moondoom/appsecgate-mcp:0.1.0
```

## Documentation

- [Agent deployment guide](docs/deploy-agents.md) — all four clients, verification steps, troubleshooting
- [Master + edge deployment](docs/deploy-master.md) — master server, sync, CI gate
- [Architecture](docs/architecture.md)
- [E2E test plan](docs/e2e-test-plan.md)
- [E2E report](docs/reports/e2e-report-2026-10-30.md)
- [TP-0001 Stage 2 test plan](docs/test-plans/TP-0001-ci-agent-local-llm.md)
- [TP-0001 Stage 2 experiment report](experiments/tp-0001/REPORT.md) — model benchmarks and aggregate findings
- [Product vision](docs/product-vision.md)
- [Open tasks](docs/open-tasks.md)
- [Article on Habr (RU)](https://habr.com/ru/articles/1099840/) — "Making AI agents paranoid: will MCP replace AppSec?"

## License

MIT — see [LICENSE](LICENSE). Bundled scanner rules are third-party (see
[third-party notices](mcp-server/rules/THIRD_PARTY_NOTICES.md)).

Russian version: [README.ru.md](README.ru.md).