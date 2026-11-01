# AppSecGate Agent

Reference server-agent for AppSecGate. The MVP provides deterministic `report`
mode without an LLM: it calls `scan_diff` or `scan_project`, then `check_gate`,
and emits Markdown or NDJSON.

```bash
appsecgate-agent \
  --mcp-command "docker run --rm -i --network=none --read-only -v .:/workspace:ro moondoom/appsecgate-mcp:0.1.0 --transport stdio --project /workspace" \
  --scope diff --policy block --format markdown
```

The MCP command is parsed with `shlex`; shell syntax is not supported. Report
mode exits `0` after a successful report and `2` on MCP/configuration errors.
Use classic `appsecgate-mcp ci` for enforced blocking.
