"""Тесты этапа 3: провод Rules Bundle в сканеры и реестр.

Проверяется, что адаптеры подставляют локальные пути правил в команды
(`--config`) и получают `ruleset_hash`; что реестр прокидывает resolved-правила
в адаптеры; что фильтрация по профилям работает (дизайн v1 §1.5, §3.1, §6.2).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from appsecgate_mcp.config.models import Config, RuleProfileConfig, ScannerConfig
from appsecgate_mcp.rules import (
    DistributionMode,
    ResolvedBundle,
    ResolvedRules,
)
from appsecgate_mcp.scanners.gitleaks import GitleaksAdapter
from appsecgate_mcp.scanners.registry import ScannerRegistry
from appsecgate_mcp.scanners.semgrep import SemgrepAdapter
from appsecgate_mcp.scanners.trufflehog import TruffleHogAdapter


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _semgrep_bundle(root: Path, *, tags: list[str] | None = None) -> ResolvedBundle:
    rule_file = _write(root / "opengrep" / "python.yaml", "rules: [x]\n")
    return ResolvedBundle(
        id="appsecgate/community-sast",
        scanner="semgrep",
        path=str(root / "opengrep"),
        license="MIT",
        source="internal",
        tags=tags or [],
        paths=[str(root / "opengrep")],
        files=[str(rule_file)],
    )


def _resolved(*bundles: ResolvedBundle) -> ResolvedRules:
    return ResolvedRules(
        version="1.0.0",
        distribution_mode=DistributionMode.MIT,
        ruleset_hash="sha256:deadbeef",
        bundles=list(bundles),
    )


# ----------------------------------------------------------------------
# Semgrep: пути правил из bundle
# ----------------------------------------------------------------------
def test_semgrep_uses_resolved_bundle_paths(tmp_path: Path):
    resolved = _resolved(_semgrep_bundle(tmp_path))
    adapter = SemgrepAdapter(resolved_rules=resolved)
    assert adapter._rulesets() == [str(tmp_path / "opengrep")]
    assert adapter.ruleset_hash == "sha256:deadbeef"


def test_semgrep_falls_back_to_config_rulesets(tmp_path: Path):
    # resolved без semgrep-бандлов → legacy-путь через config.rulesets.
    resolved = _resolved()
    config = ScannerConfig(rulesets=["p/security-audit"])
    adapter = SemgrepAdapter(config=config, resolved_rules=resolved)
    assert adapter._rulesets() == ["p/security-audit"]


def test_semgrep_falls_back_to_default_when_empty():
    adapter = SemgrepAdapter()
    assert adapter._rulesets() == list(adapter.default_rulesets)


# ----------------------------------------------------------------------
# Gitleaks / TruffleHog: --config из bundle
# ----------------------------------------------------------------------
def test_gitleaks_finds_toml_config(tmp_path: Path):
    toml = _write(tmp_path / "gitleaks" / "gitleaks.toml", "title = 'x'\n")
    bundle = ResolvedBundle(
        id="appsecgate/secrets",
        scanner="gitleaks",
        path=str(tmp_path / "gitleaks"),
        paths=[str(tmp_path / "gitleaks")],
        files=[str(toml)],
    )
    adapter = GitleaksAdapter(resolved_rules=_resolved(bundle))
    assert adapter._config_path() == str(toml)


def test_gitleaks_without_config_returns_none():
    assert GitleaksAdapter()._config_path() is None


def test_trufflehog_finds_detectors_config(tmp_path: Path):
    detectors = _write(tmp_path / "trufflehog" / "detectors.yaml", "detectors: []\n")
    bundle = ResolvedBundle(
        id="appsecgate/trufflehog-custom",
        scanner="trufflehog",
        path=str(tmp_path / "trufflehog"),
        paths=[str(tmp_path / "trufflehog")],
        files=[str(detectors)],
    )
    adapter = TruffleHogAdapter(resolved_rules=_resolved(bundle))
    assert adapter._config_path() == str(detectors)


@pytest.mark.asyncio
async def test_gitleaks_command_includes_config(tmp_path: Path, monkeypatch):
    toml = _write(tmp_path / "gitleaks" / "gitleaks.toml", "title = 'x'\n")
    bundle = ResolvedBundle(
        id="appsecgate/secrets",
        scanner="gitleaks",
        path=str(tmp_path / "gitleaks"),
        paths=[str(tmp_path / "gitleaks")],
        files=[str(toml)],
    )
    adapter = GitleaksAdapter(project_path=str(tmp_path), resolved_rules=_resolved(bundle))

    captured: dict[str, list[str]] = {}

    async def _fake_run(cmd, *, timeout=None):
        captured["cmd"] = list(cmd)

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        return _R()

    monkeypatch.setattr(adapter, "run", _fake_run)
    await adapter.scan(["a.py"], "file")
    cmd = captured["cmd"]
    assert "--config" in cmd
    assert str(toml) in cmd


@pytest.mark.asyncio
async def test_trufflehog_command_includes_config(tmp_path: Path, monkeypatch):
    detectors = _write(tmp_path / "trufflehog" / "detectors.yaml", "detectors: []\n")
    bundle = ResolvedBundle(
        id="appsecgate/trufflehog-custom",
        scanner="trufflehog",
        path=str(tmp_path / "trufflehog"),
        paths=[str(tmp_path / "trufflehog")],
        files=[str(detectors)],
    )
    adapter = TruffleHogAdapter(project_path=str(tmp_path), resolved_rules=_resolved(bundle))

    captured: dict[str, list[str]] = {}

    async def _fake_run(cmd, *, timeout=None):
        captured["cmd"] = list(cmd)

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        return _R()

    monkeypatch.setattr(adapter, "run", _fake_run)
    await adapter.scan(["a.py"], "file")
    cmd = captured["cmd"]
    assert "--config" in cmd
    assert str(detectors) in cmd


# ----------------------------------------------------------------------
# Реестр прокидывает resolved-правила
# ----------------------------------------------------------------------
def test_registry_passes_resolved_rules(tmp_path: Path):
    resolved = _resolved(_semgrep_bundle(tmp_path))
    config = Config()
    config.project_path = str(tmp_path)
    config.resolved_rules = resolved

    registry = ScannerRegistry.from_config(config, project_path=str(tmp_path))
    semgrep = registry.get("semgrep")
    assert semgrep is not None
    assert semgrep.ruleset_hash == "sha256:deadbeef"
    assert semgrep.resolved_rules is resolved


def test_registry_explicit_resolved_overrides_config(tmp_path: Path):
    explicit = _resolved()
    explicit.ruleset_hash = "sha256:explicit"
    config = Config()
    config.project_path = str(tmp_path)
    config.resolved_rules = _resolved(_semgrep_bundle(tmp_path))

    registry = ScannerRegistry.from_config(
        config, project_path=str(tmp_path), resolved_rules=explicit
    )
    assert registry.get("semgrep").ruleset_hash == "sha256:explicit"


# ----------------------------------------------------------------------
# Профили Semgrep (явная декларация, без автоопределения)
# ----------------------------------------------------------------------
def test_semgrep_profiles_filter_bundles_by_language(tmp_path: Path):
    py_bundle = _semgrep_bundle(tmp_path / "py", tags=["python"])
    go_bundle = _semgrep_bundle(tmp_path / "go", tags=["go"])
    config = ScannerConfig(profiles=[RuleProfileConfig(name="backend", languages=["python"])])
    adapter = SemgrepAdapter(config=config, resolved_rules=_resolved(py_bundle, go_bundle))

    paths = adapter._rulesets_for_languages(["python"])
    assert paths == [str(tmp_path / "py" / "opengrep")]


def test_semgrep_profiles_keep_generic_bundles(tmp_path: Path):
    generic = _semgrep_bundle(tmp_path / "generic", tags=["owasp"])
    py_bundle = _semgrep_bundle(tmp_path / "py", tags=["python"])
    adapter = SemgrepAdapter(resolved_rules=_resolved(generic, py_bundle))

    paths = adapter._rulesets_for_languages(["python"])
    # generic-бандл (без языкового тега) всегда включён.
    assert str(tmp_path / "generic" / "opengrep") in paths
    assert str(tmp_path / "py" / "opengrep") in paths


def test_semgrep_profiles_unknown_language_falls_back(tmp_path: Path):
    py_bundle = _semgrep_bundle(tmp_path / "py", tags=["python"])
    adapter = SemgrepAdapter(resolved_rules=_resolved(py_bundle))
    # Язык без маппинга → безопасный откат к полному набору.
    assert adapter._rulesets_for_languages(["cobol"]) == [str(tmp_path / "py" / "opengrep")]


@pytest.mark.asyncio
async def test_semgrep_profiled_scan_runs_per_profile(tmp_path: Path, monkeypatch):
    backend = _write(tmp_path / "backend" / "app.py", "print(1)\n")
    frontend = _write(tmp_path / "frontend" / "app.js", "console.log(1)\n")
    py_bundle = _semgrep_bundle(tmp_path / "py", tags=["python"])
    config = ScannerConfig(
        profiles=[
            RuleProfileConfig(name="backend", path="backend", languages=["python"]),
        ]
    )
    adapter = SemgrepAdapter(
        project_path=str(tmp_path),
        config=config,
        resolved_rules=_resolved(py_bundle),
    )

    runs: list[list[str]] = []

    async def _fake_run(cmd, *, timeout=None):
        runs.append(list(cmd))

        class _R:
            returncode = 0
            stdout = ""

        return _R()

    monkeypatch.setattr(adapter, "run", _fake_run)
    await adapter.scan(["backend/app.py", "frontend/app.js"], "file")
    # Два прогона: профиль backend + остаток (frontend) полным набором.
    assert len(runs) == 2
    assert str(backend) in runs[0] or "backend/app.py" in runs[0]
    assert str(frontend) in runs[1] or "frontend/app.js" in runs[1]
