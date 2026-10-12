"""Тесты нормализации file_path в get_scan_history."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from appsecgate_mcp import server


class _FakeShownStore:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.requested: list[str] = []

    async def get_by_file(self, file_path: str) -> list[dict]:
        self.requested.append(file_path)
        return [r for r in self.rows if r["file_path"] == file_path]

    async def get_all(self, limit: int = 100) -> list[dict]:
        return self.rows[:limit]


def _make_project(tmp_path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    return project


def _patch_session(monkeypatch, project, store):
    state = SimpleNamespace(project_path=str(project), shown_store=store)

    async def fake_ensure(project_path=None):
        return state

    monkeypatch.setattr(server, "_ensure_session", fake_ensure)


def test_relative_project_path_normalizes_forms(tmp_path):
    project = _make_project(tmp_path)
    target = str(project / "src" / "a.py")
    expected = "src/a.py"
    assert server._relative_project_path("src/a.py", str(project)) == expected
    assert server._relative_project_path("./src/a.py", str(project)) == expected
    assert server._relative_project_path(target, str(project)) == expected


def test_relative_project_path_rejects_outside(tmp_path):
    project = _make_project(tmp_path)
    with pytest.raises(ValueError, match="outside project"):
        server._relative_project_path("/etc/passwd", str(project))


async def test_history_same_result_for_absolute_and_relative(tmp_path, monkeypatch):
    project = _make_project(tmp_path)
    rows = [{"file_path": "src/a.py", "fingerprint": "fp1"}]
    store = _FakeShownStore(rows)
    _patch_session(monkeypatch, project, store)

    rel_out = await server.get_scan_history(file_path="src/a.py")
    abs_out = await server.get_scan_history(file_path=str(project / "src" / "a.py"))

    assert rel_out == abs_out
    assert rel_out["count"] == 1
    assert store.requested == ["src/a.py", "src/a.py"]


async def test_history_outside_project_returns_error(tmp_path, monkeypatch):
    project = _make_project(tmp_path)
    store = _FakeShownStore()
    _patch_session(monkeypatch, project, store)

    out = await server.get_scan_history(file_path="/etc/passwd")

    assert out["status"] == "error"
    assert "outside project" in out["reason"]
    assert out["items"] == []
    assert store.requested == []


async def test_history_without_file_path_returns_all(tmp_path, monkeypatch):
    project = _make_project(tmp_path)
    rows = [{"file_path": "src/a.py", "fingerprint": "fp1"}]
    store = _FakeShownStore(rows)
    _patch_session(monkeypatch, project, store)

    out = await server.get_scan_history(limit=10)

    assert out["count"] == 1
    assert out["items"] == rows


async def test_history_items_are_relative_even_if_stored_absolute(tmp_path, monkeypatch):
    project = _make_project(tmp_path)
    absolute = str(project / "src" / "a.py")
    store = _FakeShownStore([{"file_path": absolute, "fingerprint": "fp1"}])
    _patch_session(monkeypatch, project, store)

    out = await server.get_scan_history(limit=10)

    assert out["count"] == 1
    assert out["items"][0]["file_path"] == "src/a.py"
    assert str(project) not in out["items"][0]["file_path"]


async def test_history_drops_rows_outside_project(tmp_path, monkeypatch):
    project = _make_project(tmp_path)
    rows = [
        {"file_path": "src/a.py", "fingerprint": "fp1"},
        {"file_path": "/etc/passwd", "fingerprint": "fp2"},
    ]
    store = _FakeShownStore(rows)
    _patch_session(monkeypatch, project, store)

    out = await server.get_scan_history(limit=10)

    assert out["count"] == 1
    assert [i["fingerprint"] for i in out["items"]] == ["fp1"]
