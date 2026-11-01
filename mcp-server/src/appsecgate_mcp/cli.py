"""Общая точка входа режимов ``serve``, ``sync``, ``ci`` и ``agent``."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    command = args[0] if args else None

    if command == "serve":
        from appsecgate_mcp.server.cli import serve_main

        raise SystemExit(serve_main(args[1:]))
    if command == "sync":
        from appsecgate_mcp.sync.cli import sync_main

        raise SystemExit(sync_main(args[1:]))
    if command == "ci":
        from appsecgate_mcp.server.ci import ci_main

        raise SystemExit(ci_main(args[1:]))
    if command == "hook":
        from appsecgate_mcp.hooks import hook_main

        raise SystemExit(hook_main(args[1:]))
    if command == "agent":
        from appsecgate_mcp.agent.cli import agent_main

        raise SystemExit(agent_main(args[1:]))

    from appsecgate_mcp.server import main as legacy_serve_main

    legacy_serve_main()


if __name__ == "__main__":
    main()
