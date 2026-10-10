"""Тесты `BaseScanner.scan_source` — выбор директории-источника сканера.

В режиме `project` координатор передаёт один путь-директорию (весь проект
или конкретную папку), и сканеры, гуляющие по ФС, должны брать именно её.
"""

from __future__ import annotations

from secgate_mcp.scanners.gitleaks import GitleaksAdapter
from secgate_mcp.scanners.trivy import TrivyAdapter
from secgate_mcp.scanners.trufflehog import TruffleHogAdapter


def test_project_mode_absolute_dir(tmp_path):
    adapter = GitleaksAdapter(project_path=str(tmp_path))
    assert adapter.scan_source([str(tmp_path / "src")], "project") == str(tmp_path / "src")


def test_project_mode_relative_dir(tmp_path):
    adapter = TrivyAdapter(project_path=str(tmp_path))
    assert adapter.scan_source(["src"], "project") == str(tmp_path / "src")


def test_non_project_mode_uses_project_root(tmp_path):
    adapter = TruffleHogAdapter(project_path=str(tmp_path))
    assert adapter.scan_source(["a.py", "b.py"], "file") == str(tmp_path)
    assert adapter.scan_source(["a.py"], "diff") == str(tmp_path)


def test_project_mode_without_files_falls_back_to_root(tmp_path):
    adapter = GitleaksAdapter(project_path=str(tmp_path))
    assert adapter.scan_source([], "project") == str(tmp_path)
