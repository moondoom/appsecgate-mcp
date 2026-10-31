"""State machine shown_findings (ADR-0005 §2.2) и negative-merge (store-уровень).

Positive-merge (найдено) и negative-merge (не найдено в охвате) реализованы
в ``ShownFindingsStore``: переходы ``SHOWN``/``POTENTIALLY_FIXED``/
``REOPENED`` + ``missed_scan_count`` + branch-фильтр (§2.4).
"""

from __future__ import annotations

from appsecgate_mcp.models.finding import Category, Finding, Severity
from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.stores import FindingIdentityStore, ShownFindingsStore


def _finding(fp: str, *, file_path: str = "a.py") -> Finding:
    return Finding(
        fingerprint=fp,
        rule_id="test.rule",
        severity=Severity.HIGH,
        file_path=file_path,
        line_start=1,
        line_end=1,
        message="m",
        scanner="semgrep",
        category=Category.SAST,
        snippet="x = 1",
    )


async def _row(shown: ShownFindingsStore, fp: str) -> dict:
    row = await shown.find(fp)
    assert row is not None, f"finding {fp} not found"
    return row


async def _store(tmp_path, project_id: str = "pid-1") -> ShownFindingsStore:
    db = Database(tmp_path / "shown.db")
    db.connect()
    # find() джойнит finding_identity по fingerprint (ADR-0005 §2.8, К1).
    FindingIdentityStore(db).init_schema()
    shown = ShownFindingsStore(db, project_id)
    shown.init_schema()
    return shown


async def test_positive_new_finding_is_shown(tmp_path):
    """Новая находка → SHOWN: scan_count=1, missed_scan_count=0, *_seen_* заполнены."""
    shown = await _store(tmp_path)
    await shown.record_shown(_finding("fp-1"), branch="main", commit="c1")
    row = await _row(shown, "fp-1")
    assert row["status"] == "SHOWN"
    assert row["scan_count"] == 1
    assert row["missed_scan_count"] == 0
    assert row["first_seen_branch"] == "main"
    assert row["last_seen_branch"] == "main"
    assert row["last_seen_commit"] == "c1"
    assert row["first_seen_at"] is not None
    # К3: *_shown_* заполняются mark_shown() (PR-C), не positive-merge.
    assert row["first_shown_at"] is None
    assert row["show_count"] == 0


async def test_positive_reaffirmed_shown_increments_scan_count(tmp_path):
    """SHOWN → SHOWN (reaffirmed): scan_count++, missed_scan_count остаётся 0."""
    shown = await _store(tmp_path)
    await shown.record_shown(_finding("fp-1"), branch="main")
    await shown.record_shown(_finding("fp-1"), branch="main")
    row = await _row(shown, "fp-1")
    assert row["status"] == "SHOWN"
    assert row["scan_count"] == 2
    assert row["missed_scan_count"] == 0


async def test_positive_potentially_fixed_back_to_shown(tmp_path):
    """POTENTIALLY_FIXED найден снова → SHOWN, missed_scan_count сброшен."""
    shown = await _store(tmp_path)
    await shown.record_shown(_finding("fp-1"), branch="main")
    await shown.mark_missing([("fp-1", "POTENTIALLY_FIXED", 1)])
    assert (await _row(shown, "fp-1"))["status"] == "POTENTIALLY_FIXED"

    await shown.record_shown(_finding("fp-1"), branch="main")
    row = await _row(shown, "fp-1")
    assert row["status"] == "SHOWN"
    assert row["missed_scan_count"] == 0
    assert row["scan_count"] == 2


async def test_positive_fixed_reopens(tmp_path):
    """FIXED найден снова → REOPENED (регрессия, К4)."""
    shown = await _store(tmp_path)
    await shown.record_shown(_finding("fp-1"), branch="main")
    await shown.set_status("fp-1", "FIXED", confirmed_by="verify_fix")
    await shown.record_shown(_finding("fp-1"), branch="main")
    row = await _row(shown, "fp-1")
    assert row["status"] == "REOPENED"
    assert row["missed_scan_count"] == 0


async def test_negative_shown_to_potentially_fixed(tmp_path):
    """SHOWN не найден в охвате → POTENTIALLY_FIXED, missed_scan_count=1."""
    shown = await _store(tmp_path)
    await shown.record_shown(_finding("fp-1"), branch="main")
    await shown.mark_missing([("fp-1", "POTENTIALLY_FIXED", 1)])
    row = await _row(shown, "fp-1")
    assert row["status"] == "POTENTIALLY_FIXED"
    assert row["missed_scan_count"] == 1


async def test_negative_potentially_fixed_increments(tmp_path):
    """POTENTIALLY_FIXED не найден снова → тот же статус, missed_scan_count++."""
    shown = await _store(tmp_path)
    await shown.record_shown(_finding("fp-1"), branch="main")
    await shown.mark_missing([("fp-1", "POTENTIALLY_FIXED", 1)])
    await shown.mark_missing([("fp-1", "POTENTIALLY_FIXED", 2)])
    row = await _row(shown, "fp-1")
    assert row["status"] == "POTENTIALLY_FIXED"
    assert row["missed_scan_count"] == 2


async def test_negative_reopened_to_potentially_fixed(tmp_path):
    """REOPENED не найден в охвате → POTENTIALLY_FIXED, missed_scan_count=1."""
    shown = await _store(tmp_path)
    await shown.record_shown(_finding("fp-1"), branch="main")
    await shown.set_status("fp-1", "REOPENED")
    await shown.mark_missing([("fp-1", "POTENTIALLY_FIXED", 1)])
    row = await _row(shown, "fp-1")
    assert row["status"] == "POTENTIALLY_FIXED"
    assert row["missed_scan_count"] == 1


async def test_negative_merge_does_not_touch_terminal_statuses(tmp_path):
    """FIXED/SUPPRESSED/WONT_FIX не трогаются negative-merge (К7)."""
    shown = await _store(tmp_path)
    for fp in ("fp-fixed", "fp-sup", "fp-wont"):
        await shown.record_shown(_finding(fp), branch="main")
    await shown.set_status("fp-fixed", "FIXED", confirmed_by="verify_fix")
    await shown.set_status("fp-wont", "WONT_FIX", reason="accepted")
    await shown.db.execute(
        "UPDATE shown_findings SET status='SUPPRESSED' WHERE fingerprint='fp-sup'"
    )

    await shown.mark_missing(
        [
            ("fp-fixed", "POTENTIALLY_FIXED", 1),
            ("fp-sup", "POTENTIALLY_FIXED", 1),
            ("fp-wont", "POTENTIALLY_FIXED", 1),
        ]
    )
    assert (await _row(shown, "fp-fixed"))["status"] == "FIXED"
    assert (await _row(shown, "fp-sup"))["status"] == "SUPPRESSED"
    assert (await _row(shown, "fp-wont"))["status"] == "WONT_FIX"


async def test_negative_candidates_filtered_by_branch(tmp_path):
    """Negative-merge scoped по текущей ветке (ADR-0005 §2.4)."""
    shown = await _store(tmp_path)
    await shown.record_shown(_finding("fp-1"), branch="main")
    await shown.record_shown(_finding("fp-2", file_path="b.py"), branch="feature")

    on_feature = await shown.get_negative_candidates("pid-1", ["a.py", "b.py"], "feature")
    assert [c["fingerprint"] for c in on_feature] == ["fp-2"]

    on_main = await shown.get_negative_candidates("pid-1", ["a.py", "b.py"], "main")
    assert [c["fingerprint"] for c in on_main] == ["fp-1"]

    # <unknown>: только по project_id (К10).
    all_rows = await shown.get_negative_candidates("pid-1", ["a.py", "b.py"], "<unknown>")
    assert len(all_rows) == 2


async def test_status_updated_at_on_every_transition(tmp_path, monkeypatch):
    """Каждый переход статуса обновляет status_updated_at (ADR-0005 §2.2)."""
    from appsecgate_mcp.storage import stores as stores_mod

    times = iter(
        [
            "2026-01-01T00:00:01+00:00",
            "2026-01-01T00:00:02+00:00",
            "2026-01-01T00:00:03+00:00",
        ]
    )
    monkeypatch.setattr(stores_mod, "_now_iso", lambda: next(times))
    shown = await _store(tmp_path)

    await shown.record_shown(_finding("fp-1"), branch="main")
    t1 = (await _row(shown, "fp-1"))["status_updated_at"]
    await shown.mark_missing([("fp-1", "POTENTIALLY_FIXED", 1)])
    t2 = (await _row(shown, "fp-1"))["status_updated_at"]
    await shown.record_shown(_finding("fp-1"), branch="main")
    t3 = (await _row(shown, "fp-1"))["status_updated_at"]
    assert t1 < t2 < t3
