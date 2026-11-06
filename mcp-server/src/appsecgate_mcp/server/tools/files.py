from __future__ import annotations

from pathlib import Path
from typing import Any

from appsecgate_mcp.normalization.redactor import redact_text
from appsecgate_mcp.server.app import mcp
from appsecgate_mcp.server.logging_utils import _log_tool
from appsecgate_mcp.server.session import SessionState, _resolve_inside_project
from appsecgate_mcp.server.tools.common import ensure_session

_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_LINES = 200
_MAX_OUTPUT_CHARS = 64_000
_SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".kdbx"}
_SENSITIVE_NAMES = {"id_rsa", "id_ed25519", "credentials"}


def _sensitive(path: Path) -> bool:
    name = path.name.lower()
    return (
        name == ".env"
        or name.startswith(".env.")
        or name in _SENSITIVE_NAMES
        or path.suffix.lower() in _SENSITIVE_SUFFIXES
        or "secrets" in {part.lower() for part in path.parts}
    )


def _read_file(state: SessionState, *, path: str, start_line: int, end_line: int) -> dict[str, Any]:
    try:
        resolved = _resolve_inside_project(path, state.project_path)
    except ValueError as exc:
        return {"status": "error", "reason": str(exc)}
    relative = resolved.relative_to(Path(state.project_path).resolve())
    if _sensitive(relative):
        return {"status": "error", "reason": "sensitive file reads are not allowed"}
    if not resolved.is_file():
        return {"status": "error", "reason": f"file not found: {path}"}
    if resolved.stat().st_size > _MAX_FILE_BYTES:
        return {"status": "error", "reason": "file exceeds 2 MiB limit"}
    if start_line < 1 or end_line < start_line:
        return {"status": "error", "reason": "invalid line range"}
    if end_line - start_line + 1 > _MAX_LINES:
        return {"status": "error", "reason": "line range exceeds 200 lines"}
    raw = resolved.read_bytes()
    if b"\x00" in raw:
        return {"status": "error", "reason": "binary files are not supported"}
    source = raw.decode("utf-8", errors="replace").splitlines()
    selected = source[start_line - 1 : end_line]
    lines: list[dict[str, Any]] = []
    redacted = False
    output_chars = 0
    truncated = False
    for offset, text in enumerate(selected, start=start_line):
        safe = redact_text(text)
        redacted = redacted or safe != text
        if output_chars + len(safe) > _MAX_OUTPUT_CHARS:
            truncated = True
            break
        lines.append({"line": offset, "text": safe})
        output_chars += len(safe)
    return {
        "status": "ok",
        "file_path": relative.as_posix(),
        "start_line": start_line,
        "end_line": end_line,
        "lines": lines,
        "redacted": redacted,
        "truncated": truncated or end_line < len(source),
    }


@mcp.tool()
@_log_tool
async def read_project_file(path: str, start_line: int = 1, end_line: int = 200) -> dict[str, Any]:
    """Read a bounded, redacted line range from a project file."""
    state = await ensure_session()
    return _read_file(state, path=path, start_line=start_line, end_line=end_line)
