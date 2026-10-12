"""Тесты защиты путей: пути должны оставаться внутри корня проекта."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from appsecgate_mcp import server


def _make_project(tmp_path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    target = project / "src" / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    return project, target


def test_inside_relative_path_is_allowed(tmp_path):
    project, target = _make_project(tmp_path)
    resolved = server._resolve_inside_project("src/a.py", str(project))
    assert resolved == target.resolve()


def test_inside_absolute_path_is_allowed(tmp_path):
    project, target = _make_project(tmp_path)
    resolved = server._resolve_inside_project(str(target), str(project))
    assert resolved == target.resolve()


def test_absolute_path_outside_project_is_rejected(tmp_path):
    project, _ = _make_project(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("y = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="outside project"):
        server._resolve_inside_project(str(outside), str(project))


def test_parent_traversal_is_rejected(tmp_path):
    project, _ = _make_project(tmp_path)
    with pytest.raises(ValueError, match="outside project"):
        server._resolve_inside_project("../../etc/passwd", str(project))


def test_symlink_pointing_outside_is_rejected(tmp_path):
    project, _ = _make_project(tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("token", encoding="utf-8")
    link = project / "link.txt"
    link.symlink_to(outside)
    with pytest.raises(ValueError, match="outside project"):
        server._resolve_inside_project("link.txt", str(project))


@pytest.mark.parametrize("empty", ["", "   "])
def test_empty_path_is_rejected(tmp_path, empty):
    project, _ = _make_project(tmp_path)
    with pytest.raises(ValueError, match="empty"):
        server._resolve_inside_project(empty, str(project))


async def test_scan_file_rejects_path_outside_project(tmp_path, monkeypatch):
    project, _ = _make_project(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("y = 2\n", encoding="utf-8")
    state = SimpleNamespace(project_path=str(project))

    async def fake_ensure(project_path=None):
        return state

    monkeypatch.setattr(server, "_ensure_session", fake_ensure)
    out = await server.scan_file(str(outside))

    assert "outside project" in out["error"]
    assert out["findings"] == []
