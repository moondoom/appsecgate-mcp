"""MS-5: хранение и приоритет центральной policy в ConfigLoader."""

from __future__ import annotations

import json

import pytest
import yaml

from appsecgate_mcp.config.loader import ConfigLoader
from appsecgate_mcp.config.master_policy import (
    load_master_policy,
    master_policy_path,
    validate_master_policy,
    write_master_policy,
)


def _project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / ".appsecgate-mcp").mkdir()
    (project / ".appsecgate-mcp" / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "gates": {"ci": {"wont_fix_action": "block"}},
                "rules": {"path": "/project-rules"},
            }
        ),
        encoding="utf-8",
    )
    return project


def test_master_policy_precedence_and_env_override(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("APPSECGATE_MCP_HOME", str(data_dir))
    project = _project(tmp_path)
    write_master_policy(
        data_dir,
        "p1",
        {
            "gates": {"ci": {"wont_fix_action": "skip"}},
            "rules": {"path": "/master-rules"},
        },
    )

    loader = ConfigLoader(tmp_path / "no-default.yaml")
    config = loader.load(project, project_id="p1")
    assert config.gates.ci.wont_fix_action == "skip"
    assert config.rules_path == "/master-rules"

    monkeypatch.setenv("APPSECGATE_RULES_PATH", "/env-rules")
    overridden = ConfigLoader(tmp_path / "no-default.yaml").load(project, project_id="p1")
    assert overridden.rules_path == "/env-rules"


def test_validation_layers_include_master_policy(tmp_path):
    data_dir = tmp_path / "data"
    write_master_policy(data_dir, "p1", {"gates": {"ci": {"wont_fix_action": "skip"}}})
    loader = ConfigLoader(tmp_path / "no-default.yaml")
    layers = loader.validation_layers({}, data_dir=data_dir, project_id="p1")
    assert layers["gates"]["ci"]["wont_fix_action"] == "skip"


def test_policy_null_removes_previous_file(tmp_path):
    path = master_policy_path(tmp_path, "p1")
    write_master_policy(tmp_path, "p1", {"gates": {"ci": {"new_finding_action": "info"}}})
    assert path.is_file()
    write_master_policy(tmp_path, "p1", None)
    assert not path.exists()
    assert load_master_policy(tmp_path, "p1") == {}


@pytest.mark.parametrize("section", ["network", "scanners", "stack"])
def test_policy_rejects_non_policy_sections(tmp_path, section):
    with pytest.raises(ValueError, match="forbidden sections"):
        validate_master_policy({section: {}})


def test_policy_rejects_invalid_schema(tmp_path):
    with pytest.raises(ValueError):
        write_master_policy(tmp_path, "p1", {"gates": {"ci": {"unknown": True}}})


def test_loader_rejects_corrupt_policy(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("APPSECGATE_MCP_HOME", str(data_dir))
    path = master_policy_path(data_dir, "p1")
    path.parent.mkdir(parents=True)
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot read master policy"):
        ConfigLoader(tmp_path / "no-default.yaml").load(_project(tmp_path), project_id="p1")


def test_policy_project_id_cannot_escape_data_dir(tmp_path):
    with pytest.raises(ValueError, match="not safe"):
        master_policy_path(tmp_path, "../other")


def test_policy_file_is_valid_json(tmp_path):
    write_master_policy(tmp_path, "p1", {"rules": {"distribution_mode": "commercial"}})
    path = master_policy_path(tmp_path, "p1")
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "rules": {"distribution_mode": "commercial"}
    }
