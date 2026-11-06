from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest
import yaml

from appsecgate_mcp.rules import fetch
from appsecgate_mcp.rules.fetch_cli import rules_main


def _archive(path: Path, source: str, files: dict[str, str]) -> Path:
    archive = path / f"{source}.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        for name, content in {"LICENSE": f"{source} license\n", **files}.items():
            payload = content.encode()
            member = tarfile.TarInfo(f"{source}-revision/{name}")
            member.size = len(payload)
            output.addfile(member, io.BytesIO(payload))
    return archive


def _mock_downloads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    archives = {
        "semgrep": _archive(
            tmp_path,
            "semgrep",
            {
                "python/security/a.yaml": "rules:\n  - id: shared-rule\n  - id: python-a\n",
                "rust/security/a.yaml": "rules:\n  - id: rust-a\n",
                "generic/a.yaml": "rules:\n  - id: generic-a\n",
            },
        ),
        "trailofbits": _archive(
            tmp_path,
            "trailofbits",
            {
                "python/a.yaml": "rules:\n  - id: shared-rule\n",
                "python/b.yaml": "rules:\n  - id: tob-python-b\n",
                "go/a.yaml": "rules:\n  - id: tob-go-a\n",
            },
        ),
    }

    def download(source, cache_dir):
        return archives[source.name], source.name + "-hash"

    monkeypatch.setattr(fetch, "_download", download)


def test_install_filters_deduplicates_and_preserves_custom_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    _mock_downloads(monkeypatch, tmp_path)
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    custom = {"id": "user/custom", "scanner": "semgrep", "path": "/custom"}
    (rules_dir / "manifest.yaml").write_text(
        yaml.safe_dump({"version": "1", "bundles": [custom]}), encoding="utf-8"
    )

    result = fetch.install_rules(
        tmp_path, ["semgrep", "trailofbits"], ["python"], accept_licenses=True
    )

    assert (rules_dir / "external-semgrep/python/security/a.yaml").is_file()
    assert not (rules_dir / "external-semgrep/rust").exists()
    assert (rules_dir / "external-semgrep/generic/a.yaml").is_file()
    assert (rules_dir / "external-semgrep/LICENSE").is_file()
    assert (rules_dir / "external-trailofbits/python/b.yaml").is_file()
    assert not (rules_dir / "external-trailofbits/python/a.yaml").exists()
    assert not (rules_dir / "external-trailofbits/go").exists()
    assert result["sources"]["trailofbits"]["duplicates"][0]["rule_ids"] == ["shared-rule"]
    manifest = yaml.safe_load((rules_dir / "manifest.yaml").read_text())
    assert custom in manifest["bundles"]
    assert {b["id"] for b in manifest["bundles"]} == {
        "user/custom",
        "external/semgrep",
        "external/trailofbits",
    }


def test_install_is_idempotent_and_remove_preserves_custom(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    _mock_downloads(monkeypatch, tmp_path)
    first = fetch.install_rules(tmp_path, ["semgrep"], ["python"], accept_licenses=True)
    calls = 0
    original = fetch._extract_source

    def unexpected(*args):
        nonlocal calls
        calls += 1
        return original(*args)

    monkeypatch.setattr(fetch, "_extract_source", unexpected)
    second = fetch.install_rules(tmp_path, ["semgrep"], ["python"], accept_licenses=True)
    assert first == second
    assert calls == 0

    remaining = fetch.remove_rules(tmp_path, ["semgrep"])
    assert remaining["sources"] == {}
    assert not (tmp_path / "rules/external-semgrep").exists()
    assert yaml.safe_load((tmp_path / "rules/manifest.yaml").read_text())["bundles"] == []


def test_install_requires_license_acceptance(tmp_path: Path):
    with pytest.raises(fetch.RulesFetchError, match="accept-licenses"):
        fetch.install_rules(tmp_path, ["semgrep"], ["python"], accept_licenses=False)


def test_install_rejects_unknown_language(tmp_path: Path):
    with pytest.raises(fetch.RulesFetchError, match="unknown languages"):
        fetch.install_rules(tmp_path, ["semgrep"], ["brainfuck"], accept_licenses=True)


def test_archive_path_traversal_is_rejected(tmp_path: Path):
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        payload = b"rules: []\n"
        member = tarfile.TarInfo("root/python/../../escape.yaml")
        member.size = len(payload)
        output.addfile(member, io.BytesIO(payload))
    with pytest.raises(fetch.RulesFetchError, match="unsafe archive path"):
        fetch._selected_members(archive, ["python"])


def test_cli_list_and_profile_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys):
    _mock_downloads(monkeypatch, tmp_path)
    assert rules_main(["list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["profiles"]["agent300"] == [
        "python",
        "javascript",
        "typescript",
        "go",
        "java",
        "ruby",
        "php",
    ]
    code = rules_main(
        [
            "install",
            "--data-dir",
            str(tmp_path),
            "--source",
            "semgrep",
            "--profile",
            "agent300",
            "--accept-licenses",
        ]
    )
    assert code == 0
    assert (tmp_path / "rules/external-semgrep/python/security/a.yaml").is_file()


def test_cli_license_refusal(tmp_path: Path, capsys):
    code = rules_main(
        [
            "install",
            "--data-dir",
            str(tmp_path),
            "--source",
            "semgrep",
            "--languages",
            "python",
        ]
    )
    assert code == 2
    assert "accept-licenses" in capsys.readouterr().err
