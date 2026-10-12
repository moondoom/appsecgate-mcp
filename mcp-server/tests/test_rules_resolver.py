"""Тесты RuleResolver: overlay-слои, пути, disable/replace, ruleset_hash.

Дизайн v1 §1.5, §3.1, §3.3. Проверяется разрешение бандлов по слоям
(default → project → user), слияние без deep-merge и fail-soft поведение.
"""

from __future__ import annotations

from pathlib import Path

from appsecgate_mcp.rules.manifest import DistributionMode
from appsecgate_mcp.rules.resolver import (
    RuleResolver,
    compute_ruleset_hash,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _make_default_root(tmp_path: Path) -> Path:
    """Создаёт default-root с манифестом и одним бандлом-директорией."""
    root = tmp_path / "opt-rules"
    bundle_dir = root / "opengrep-community"
    _write(bundle_dir / "python.yaml", "rules: [a]\n")
    _write(bundle_dir / "go.yaml", "rules: [b]\n")
    manifest = f"""
version: "1.0.0"
distribution_mode: "mit"
bundles:
  - id: "appsecgate/community-sast"
    scanner: "semgrep"
    path: "{bundle_dir}"
    license: "MIT AND LGPL-3.0-only"
    source: "https://github.com/qodana/opengrep-sast-rules"
    redistribution: "allowed"
    tags: ["generic"]
"""
    _write(root / "manifest.yaml", manifest)
    return root


# ----------------------------------------------------------------------
# Базовое разрешение
# ----------------------------------------------------------------------
def test_resolves_default_bundle_directory(tmp_path: Path):
    root = _make_default_root(tmp_path)
    resolved = RuleResolver(default_root=root).resolve()

    assert resolved.version == "1.0.0"
    assert resolved.distribution_mode is DistributionMode.MIT
    bundles = resolved.bundles_for_scanner("semgrep")
    assert len(bundles) == 1
    assert bundles[0].id == "appsecgate/community-sast"
    assert bundles[0].rules_count == 2
    # Единственная директория-источник → отдаём её целиком.
    assert resolved.paths_for_scanner("semgrep") == [str(root / "opengrep-community")]


def test_missing_default_manifest_is_soft(tmp_path: Path):
    resolved = RuleResolver(default_root=tmp_path / "nope").resolve()
    assert resolved.bundles == []
    assert any("manifest" in w for w in resolved.warnings)
    assert resolved.ruleset_hash.startswith("sha256:")


def test_missing_bundle_on_disk_warns(tmp_path: Path):
    root = tmp_path / "opt-rules"
    _write(
        root / "manifest.yaml",
        """
version: "1.0.0"
bundles:
  - id: "x"
    scanner: "semgrep"
    path: "{}"
""".format(root / "does-not-exist"),
    )
    resolved = RuleResolver(default_root=root).resolve()
    assert resolved.bundles == []
    assert any("not found on disk" in w for w in resolved.warnings)


# ----------------------------------------------------------------------
# Overlay-слои (без deep-merge)
# ----------------------------------------------------------------------
def test_project_overlay_file_replaces_by_name(tmp_path: Path):
    root = _make_default_root(tmp_path)
    project_root = tmp_path / "proj" / ".appsecgate-mcp" / "rules"
    # Заменяем python.yaml и добавляем новый файл.
    _write(project_root / "opengrep-community" / "python.yaml", "rules: [patched]\n")
    _write(project_root / "opengrep-community" / "rust.yaml", "rules: [c]\n")

    resolved = RuleResolver(default_root=root, project_root=project_root).resolve()
    bundle = resolved.bundles_for_scanner("semgrep")[0]

    # 3 файла: go.yaml (default) + python.yaml (overlay) + rust.yaml (overlay).
    assert bundle.rules_count == 3
    overlay_python = project_root / "opengrep-community" / "python.yaml"
    assert str(overlay_python) in bundle.files
    # Две директории-источника → отдаём список файлов, не директорию.
    assert str(root / "opengrep-community") not in resolved.paths_for_scanner("semgrep")


def test_user_overlay_wins_over_project(tmp_path: Path):
    root = _make_default_root(tmp_path)
    project_root = tmp_path / "proj-rules"
    user_root = tmp_path / "user-rules"
    _write(project_root / "opengrep-community" / "python.yaml", "rules: [project]\n")
    _write(user_root / "opengrep-community" / "python.yaml", "rules: [user]\n")

    resolved = RuleResolver(
        default_root=root, project_root=project_root, user_root=user_root
    ).resolve()
    bundle = resolved.bundles_for_scanner("semgrep")[0]
    # python.yaml взят из user-слоя (наивысший приоритет).
    assert str(user_root / "opengrep-community" / "python.yaml") in bundle.files


def test_new_bundle_from_overlay_added(tmp_path: Path):
    root = _make_default_root(tmp_path)
    project_root = tmp_path / "proj-rules"
    new_dir = project_root / "custom"
    _write(new_dir / "custom.yaml", "rules: [x]\n")
    _write(
        project_root / "manifest.yaml",
        f"""
version: "1.0.0"
bundles:
  - id: "appsecgate/custom"
    scanner: "semgrep"
    path: "{new_dir}"
""",
    )
    resolved = RuleResolver(default_root=root, project_root=project_root).resolve()
    ids = {b.id for b in resolved.bundles}
    # default-бандл сохранён, overlay-бандл добавлен.
    assert "appsecgate/community-sast" in ids
    assert "appsecgate/custom" in ids


# ----------------------------------------------------------------------
# disable / replace
# ----------------------------------------------------------------------
def test_overrides_disable_and_replace(tmp_path: Path):
    root = _make_default_root(tmp_path)
    project_root = tmp_path / "proj-rules"
    _write(
        project_root / "manifest.yaml",
        """
version: "1.0.0"
bundles: []
overrides:
  semgrep:
    disable:
      - "python.lang.security.audit.exec-use"
    replace:
      "python.lang.security.audit.subprocess-shell-true": "~/my-subprocess.yaml"
""",
    )
    resolved = RuleResolver(default_root=root, project_root=project_root).resolve()
    assert "python.lang.security.audit.exec-use" in resolved.disable_for_scanner("semgrep")
    # `~` раскрыт в абсолютный путь.
    replaced = resolved.replace["semgrep"][
        "python.lang.security.audit.subprocess-shell-true"
    ]
    assert replaced.endswith("my-subprocess.yaml")
    assert "~" not in replaced


def test_invalid_overlay_manifest_fail_soft(tmp_path: Path):
    root = _make_default_root(tmp_path)
    project_root = tmp_path / "proj-rules"
    project_root.mkdir(parents=True)
    _write(project_root / "manifest.yaml", "bundles: [unclosed\n")

    resolved = RuleResolver(default_root=root, project_root=project_root).resolve()
    # Дефолт сохранён, overlay проигнорирован с warning.
    assert len(resolved.bundles) == 1
    assert any("project overlay ignored" in w for w in resolved.warnings)


# ----------------------------------------------------------------------
# ruleset_hash
# ----------------------------------------------------------------------
def test_ruleset_hash_stable_and_content_sensitive(tmp_path: Path):
    root = _make_default_root(tmp_path)
    first = RuleResolver(default_root=root).resolve()
    second = RuleResolver(default_root=root).resolve()
    assert first.ruleset_hash == second.ruleset_hash

    # Изменение содержимого правила меняет хэш.
    _write(root / "opengrep-community" / "go.yaml", "rules: [b, c]\n")
    third = RuleResolver(default_root=root).resolve()
    assert third.ruleset_hash != first.ruleset_hash


def test_ruleset_hash_mode_sensitive(tmp_path: Path):
    root = _make_default_root(tmp_path)
    mit = RuleResolver(default_root=root).resolve(distribution_mode=DistributionMode.MIT)
    commercial = RuleResolver(default_root=root).resolve(
        distribution_mode=DistributionMode.COMMERCIAL
    )
    assert mit.ruleset_hash != commercial.ruleset_hash


def test_compute_ruleset_hash_includes_scanner_version_and_missing(tmp_path: Path):
    f = _write(tmp_path / "a.yaml", "x: 1\n")
    base = compute_ruleset_hash("1.0.0", [str(f)], "1.2.3", DistributionMode.MIT)
    other = compute_ruleset_hash("1.0.0", [str(f)], "1.2.4", DistributionMode.MIT)
    assert base != other
    # Отсутствующий файл не роняет хэш.
    missing = compute_ruleset_hash(
        "1.0.0", [str(tmp_path / "nope.yaml")], "1.2.3", DistributionMode.MIT
    )
    assert missing.startswith("sha256:")


def test_bundles_summary(tmp_path: Path):
    root = _make_default_root(tmp_path)
    resolved = RuleResolver(default_root=root).resolve()
    summary = resolved.bundles_summary()
    assert summary == [{"id": "appsecgate/community-sast", "rules_count": 2}]
