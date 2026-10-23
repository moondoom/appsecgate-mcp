# Deploying AppSecGate MCP for AI Agents

Guide for connecting the MCP server to AI coding agents (task T2,
`docs/open-tasks.md`). Configuration examples are provided in this document;
the only actively maintained config is
`.continue/mcpServers/appsecgate.yaml` (the `.continue/` directory is in
`.gitignore`, so the file remains local and is never committed).

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

## 3. Common config block

All client examples share the same Docker command:

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

Working config: `.continue/mcpServers/appsecgate.yaml` (local file,
`.continue/` is in `.gitignore`). Copy it to
`<project>/.continue/mcpServers/` (or `~/.continue/mcpServers/`):

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