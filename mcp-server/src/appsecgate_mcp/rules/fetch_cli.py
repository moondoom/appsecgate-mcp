"""CLI пользовательской загрузки внешних правил (host-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from appsecgate_mcp.rules.fetch import (
    PROFILES,
    SOURCES,
    RulesFetchError,
    available_languages,
    install_rules,
    remove_rules,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="appsecgate-mcp rules",
        description="Download user-selected external rules on the host; MCP stays offline",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List sources, licenses, profiles and languages")
    for command in ("install", "remove"):
        sub = commands.add_parser(command)
        sub.add_argument("--data-dir", type=Path, default=Path.home() / ".appsecgate-mcp")
        sub.add_argument("--source", action="append", choices=sorted(SOURCES), required=True)
        if command == "install":
            selection = sub.add_mutually_exclusive_group(required=True)
            selection.add_argument("--profile", choices=sorted(PROFILES))
            selection.add_argument("--languages", help="Comma-separated explicit language list")
            sub.add_argument("--accept-licenses", action="store_true")
    return parser


def _list() -> dict[str, object]:
    return {
        "sources": [
            {
                "name": source.name,
                "repository": source.repository,
                "revision": source.revision,
                "license": source.license,
                "languages": sorted(source.language_dirs),
                "common_directories": list(source.common_dirs),
            }
            for source in SOURCES.values()
        ],
        "profiles": {name: list(languages) for name, languages in PROFILES.items()},
        "languages": available_languages(),
        "required_environment": "APPSECGATE_RULES_DISTRIBUTION_MODE=commercial",
    }


def rules_main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "list":
        result: dict[str, object] = _list()
    else:
        try:
            if args.command == "remove":
                result = remove_rules(args.data_dir, args.source)
            else:
                languages = (
                    list(PROFILES[args.profile])
                    if args.profile
                    else [
                        item.strip().lower() for item in args.languages.split(",") if item.strip()
                    ]
                )
                if not languages:
                    raise RulesFetchError("language list must not be empty")
                result = install_rules(
                    args.data_dir,
                    args.source,
                    languages,
                    accept_licenses=args.accept_licenses,
                )
        except RulesFetchError as exc:
            print(f"appsecgate rules: error: {exc}", file=sys.stderr)
            return 2
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0
