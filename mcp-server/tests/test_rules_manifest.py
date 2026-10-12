"""Тесты парсинга `manifest.yaml` Rules Bundle."""

from __future__ import annotations

from pathlib import Path

import pytest

from appsecgate_mcp.rules.manifest import (
    DistributionMode,
    Redistribution,
    load_manifest,
    load_manifest_soft,
)

# Манифест из дизайна v1 (§1.4).
_VALID_MANIFEST = """
version: "1.0.0"
distribution_mode: "mit"

bundles:
  - id: "appsecgate/community-sast"
    scanner: "semgrep"
    path: "/opt/appsecgate/rules/opengrep-community"
    license: "MIT AND LGPL-3.0-only"
    source: "https://github.com/qodana/opengrep-sast-rules"
    redistribution: "allowed"
    tags: ["owasp", "generic", "py", "js", "go", "iac"]

  - id: "appsecgate/trufflehog-custom"
    scanner: "trufflehog"
    path: "/opt/appsecgate/rules/trufflehog"
    license: "N/A (config only)"
    source: "internal"
    redistribution: "allowed"
    min_scanner_version: "3.82.0"
    tags: ["secrets"]
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "manifest.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_parses_valid_manifest(tmp_path: Path):
    manifest = load_manifest(_write(tmp_path, _VALID_MANIFEST))
    assert manifest.version == "1.0.0"
    assert manifest.distribution_mode is DistributionMode.MIT
    assert len(manifest.bundles) == 2

    sast = manifest.bundles[0]
    assert sast.id == "appsecgate/community-sast"
    assert sast.scanner == "semgrep"
    assert sast.redistribution is Redistribution.ALLOWED
    assert "owasp" in sast.tags

    th = manifest.bundles[1]
    assert th.min_scanner_version == "3.82.0"


def test_defaults_applied_when_fields_missing(tmp_path: Path):
    manifest = load_manifest(_write(tmp_path, "bundles: []\n"))
    assert manifest.version == "0.0.0"
    assert manifest.distribution_mode is DistributionMode.MIT
    assert manifest.bundles == []
    assert manifest.overrides is None


def test_parses_overrides(tmp_path: Path):
    text = """
version: "1.0.0"
distribution_mode: mit
bundles: []
overrides:
  semgrep:
    disable:
      - "python.lang.security.audit.exec-use"
    replace:
      "python.lang.security.audit.subprocess-shell-true": "~/my-subprocess.yaml"
"""
    manifest = load_manifest(_write(tmp_path, text))
    assert manifest.overrides is not None
    semgrep = manifest.overrides.for_scanner("semgrep")
    assert "python.lang.security.audit.exec-use" in semgrep.disable
    assert (
        semgrep.replace["python.lang.security.audit.subprocess-shell-true"]
        == "~/my-subprocess.yaml"
    )
    # Неизвестный сканер → пустой блок, без падения.
    assert manifest.overrides.for_scanner("gitleaks").disable == []


def test_missing_file_raises(tmp_path: Path):
    from appsecgate_mcp.rules.manifest import ManifestError

    with pytest.raises(ManifestError):
        load_manifest(tmp_path / "nope.yaml")


def test_invalid_yaml_soft_returns_warning(tmp_path: Path):
    path = _write(tmp_path, "bundles: [unclosed\n")
    manifest, warning = load_manifest_soft(path)
    assert manifest is None
    assert warning is not None


def test_invalid_schema_soft_returns_warning(tmp_path: Path):
    # redistribution — enum, значение вне допустимых → ошибка схемы.
    text = """
version: "1.0.0"
bundles:
  - id: x
    scanner: semgrep
    path: /x
    redistribution: forbidden
"""
    manifest, warning = load_manifest_soft(_write(tmp_path, text))
    assert manifest is None
    assert warning is not None


def test_soft_success_returns_manifest(tmp_path: Path):
    manifest, warning = load_manifest_soft(_write(tmp_path, _VALID_MANIFEST))
    assert manifest is not None
    assert warning is None
