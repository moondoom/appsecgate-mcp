from __future__ import annotations

from typing import Any

from appsecgate_mcp.agent.controller import AgentController

_MANIFEST_EXACT = {
    "go.mod",
    "go.sum",
    "package.json",
    "package-lock.json",
    "pom.xml",
    "pyproject.toml",
    "poetry.lock",
    "Pipfile",
    "Pipfile.lock",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.toml",
    "Cargo.lock",
    "Gemfile",
    "Gemfile.lock",
    "composer.json",
    "build.gradle",
    "build.gradle.kts",
}


def _manifest_paths(chunk: list[str], findings: dict[str, dict[str, Any]]) -> list[str]:
    paths = set()
    for fid in chunk:
        finding = findings.get(fid) or {}
        path = finding.get("file_path") or ""
        name = path.rsplit("/", 1)[-1]
        if name.startswith("requirements") or name in _MANIFEST_EXACT:
            paths.add(path)
    return sorted(paths)[:4]


async def _manifest_contents(
    controller: AgentController, chunk: list[str], findings: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    contents: dict[str, Any] = {}
    for path in _manifest_paths(chunk, findings):
        lines: list[str] = []
        truncated = False
        for start in (1, 201):
            result = await controller.call(
                "read_project_file",
                {"path": path, "start_line": start, "end_line": start + 199},
            )
            if result.get("status") != "ok":
                break
            lines.extend(f"{item['line']}: {item['text']}" for item in result["lines"])
            truncated = result["truncated"]
            if not truncated:
                break
        if lines:
            contents[path] = {
                "content": "\n".join(lines)[:20_000],
                "truncated": truncated,
            }
    return contents


async def _build_payload(
    controller: AgentController,
    project_context: dict[str, str],
    chunk: list[str],
    findings: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    contexts = await controller.call("get_fix_context_batch", {"finding_ids": chunk})
    manifests = await _manifest_contents(controller, chunk, findings)
    return {
        "task": "Submit one verdict for every provided finding ID.",
        "project_context": project_context,
        "findings": [findings[fid] for fid in chunk if fid in findings],
        "contexts": contexts,
        "manifest_files": manifests,
    }
