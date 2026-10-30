"""Тесты этапа 2: модели конфига + провод Rules Bundle в ConfigLoader.

Проверяется, что `ConfigLoader.load()` отдаёт resolved-правила и warnings,
что `network.mode` парсится, и что лицензионный гвард ловит `restricted`
в режиме `mit` (дизайн v1 §2, §3.3).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from appsecgate_mcp.config.loader import ConfigLoader
from appsecgate_mcp.config.models import Config
from appsecgate_mcp.rules import DistributionMode


def _write_default_config(path: Path, *, distribution_mode: str = "mit") -> Path:
    """Пишет default.yaml с блоком rules и возвращает путь."""
    data = {
        "version": 2,
        "rules": {"path": "", "distribution_mode": distribution_mode},
        "network": {"mode": "offline", "sync": {"max_db_age_days": 30}},
    }
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _write_manifest(rules_root: Path, *, redistribution: str = "allowed") -> Path:
    """Создаёт rules-root с manifest.yaml и одним бандлом-директорией."""
    bundle_dir = rules_root / "semgrep-custom"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "base.yaml").write_text("rules: [x]\n", encoding="utf-8")
    manifest = {
        "version": "1.0.0",
        "distribution_mode": "mit",
        "bundles": [
            {
                "id": "appsecgate/base",
                "scanner": "semgrep",
                "path": str(bundle_dir),
                "license": "MIT",
                "redistribution": redistribution,
            }
        ],
    }
    (rules_root / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8"
    )
    return rules_root


def test_config_defaults_have_rules_and_network():
    config = Config()
    assert config.rules.distribution_mode is DistributionMode.MIT
    assert config.network.mode == "offline"
    assert config.network.is_online() is False
    assert config.resolved_rules is None


def test_loader_resolves_rules(tmp_path: Path):
    default = _write_default_config(tmp_path / "default.yaml")
    rules_root = _write_manifest(tmp_path / "rules")
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".appsecgate-mcp").mkdir()
    (project / ".appsecgate-mcp" / "config.yaml").write_text(
        yaml.safe_dump({"rules": {"path": str(rules_root)}}), encoding="utf-8"
    )

    loader = ConfigLoader(default_config_path=default)
    config = loader.load(project)

    assert config.resolved_rules is not None
    assert config.resolved_rules.version == "1.0.0"
    assert config.resolved_rules.ruleset_hash.startswith("sha256:")
    assert config.resolved_rules.bundles_for_scanner("semgrep")
    assert config.rules_warnings == []


def test_loader_network_mode_online():
    config = Config.model_validate({"network": {"mode": "Online"}})
    assert config.network.is_online() is True


def test_license_guard_blocks_restricted_under_mit(tmp_path: Path):
    default = _write_default_config(tmp_path / "default.yaml", distribution_mode="mit")
    rules_root = _write_manifest(tmp_path / "rules", redistribution="restricted")
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".appsecgate-mcp").mkdir()
    (project / ".appsecgate-mcp" / "config.yaml").write_text(
        yaml.safe_dump({"rules": {"path": str(rules_root)}}), encoding="utf-8"
    )

    loader = ConfigLoader(default_config_path=default)
    config = loader.load(project)

    # Гвард сообщает об ошибке через warnings, но не роняет загрузку.
    assert config.resolved_rules is not None
    assert any("restricted" in w for w in config.rules_warnings)


def test_loader_missing_rules_is_fail_soft(tmp_path: Path):
    default = _write_default_config(tmp_path / "default.yaml")
    project = tmp_path / "proj"
    project.mkdir()

    loader = ConfigLoader(default_config_path=default)
    config = loader.load(project)

    # rules_root пуст → дефолт /opt/appsecgate/rules отсутствует.
    assert config.resolved_rules is not None
    assert config.resolved_rules.bundles == []
    assert config.rules_warnings  # warning про отсутствующий manifest


def test_load_config_file_resolves_rules(tmp_path: Path):
    default = _write_default_config(tmp_path / "default.yaml")
    rules_root = _write_manifest(tmp_path / "rules")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump({"rules": {"path": str(rules_root)}}), encoding="utf-8")

    loader = ConfigLoader(default_config_path=default)
    config = loader.load_config_file(config_file)

    assert config.resolved_rules is not None
    assert config.resolved_rules.version == "1.0.0"


def test_config_rejects_unknown_top_level_field():
    """T6: `extra="forbid"` — неизвестное поле ломает валидацию, а не дропается."""
    with pytest.raises(ValidationError):
        Config.model_validate({"version": 2, "totally_unknown_field": 42})


def test_config_rejects_unknown_nested_field():
    """T6: лишнее поле отвергается и на вложенных уровнях."""
    with pytest.raises(ValidationError):
        Config.model_validate({"scanners": {"sast": {"bogus_option": 1}}})


def test_env_override_applies_only_to_existing_paths(tmp_path: Path, monkeypatch):
    """T6: документированный env-override работает, а инфраструктурные
    APPSECGATE_*-переменные не просачиваются в конфиг как mcp.home (иначе
    `extra="forbid"` уронил бы загрузку)."""
    default = tmp_path / "default.yaml"
    default.write_text(
        yaml.safe_dump({"version": 2, "scanners": {"sast": {"enabled": True, "tool": "semgrep"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("APPSECGATE_SCANNERS_SAST_ENABLED", "false")
    monkeypatch.setenv("APPSECGATE_MCP_HOME", str(tmp_path / "home"))

    config = ConfigLoader(default_config_path=default).load(tmp_path / "proj")

    assert config.scanners.sast.enabled is False
    assert "mcp" not in config.model_dump()
