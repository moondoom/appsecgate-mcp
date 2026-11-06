from __future__ import annotations

import json

from appsecgate_mcp.sync.export import ExportResult
from appsecgate_mcp.sync.triage import append_triage_events


def test_append_triage_events_filters_project(tmp_path):
    events = [
        {
            "client_event_id": "event-1",
            "project_key": "p1",
            "event_type": "triage_verdicted",
            "fp": "fp-1",
        },
        {
            "client_event_id": "event-2",
            "project_key": "p2",
            "event_type": "triage_verdicted",
            "fp": "fp-2",
        },
    ]
    (tmp_path / "triage_verdicts.ndjson").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n"
    )
    exported = ExportResult(events=[], project_count=0, finding_count=0)

    append_triage_events(exported, tmp_path, "p1")

    assert [event["client_event_id"] for event in exported.events] == ["event-1"]
    assert exported.by_event == {"triage_verdicted": 1}
