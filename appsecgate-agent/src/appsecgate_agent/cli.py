"""CLI appsecgate-agent (MVP: report mode)."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from appsecgate_agent.mcp_client import McpClient
from appsecgate_agent.report import render
from appsecgate_agent.runner import run_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="appsecgate-agent")
    parser.add_argument(
        "--mcp-command",
        default=os.environ.get("APPSECGATE_MCP_COMMAND", ""),
        help="MCP stdio command (or APPSECGATE_MCP_COMMAND)",
    )
    parser.add_argument("--scope", choices=["diff", "full"], default="diff")
    parser.add_argument("--policy", choices=["warn", "block", "escalate"], default="block")
    parser.add_argument("--format", choices=["markdown", "ndjson"], default="markdown")
    parser.add_argument("--output", help="Write report to this file instead of stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.mcp_command.strip():
        print("appsecgate-agent: --mcp-command is required", file=sys.stderr)
        return 2
    try:
        result = asyncio.run(
            run_report(McpClient(args.mcp_command), scope=args.scope, policy=args.policy)
        )
        output = render(result, args.format)
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"appsecgate-agent: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
