from __future__ import annotations

import json
from pathlib import Path

from appsecgate_mcp.sync.export import ExportResult


def append_triage_events(
    exported: ExportResult, data_dir: str | Path, project_id: str | None
) -> None:
    path = Path(data_dir) / "triage_verdicts.ndjson"
    if not path.is_file():
        return
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if project_id is not None and event.get("project_key") != project_id:
            continue
        if event.get("event_type") == "triage_verdicted":
            events.append(event)
    exported.events.extend(events)
    exported.by_event["triage_verdicted"] = exported.by_event.get("triage_verdicted", 0) + len(
        events
    )
