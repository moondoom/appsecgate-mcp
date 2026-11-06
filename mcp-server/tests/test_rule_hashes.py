from __future__ import annotations

from appsecgate_mcp.rules.hashes import compute_rule_hashes
from appsecgate_mcp.rules.resolver import ResolvedBundle, ResolvedRules


def _bundle(scanner, *files):
    return ResolvedBundle(
        id=f"{scanner}-rules",
        scanner=scanner,
        path=".",
        paths=[str(files[0])],
        files=[str(path) for path in files],
    )


def test_semgrep_rule_hash_is_stable_and_content_sensitive(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        "rules:\n  - id: demo-rule\n    pattern: $X\n    message: first\n",
        encoding="utf-8",
    )
    bundles = [_bundle("semgrep", path)]

    first = compute_rule_hashes(bundles)
    second = compute_rule_hashes(bundles)
    path.write_text(
        "rules:\n  - id: demo-rule\n    pattern: $X\n    message: changed\n",
        encoding="utf-8",
    )
    changed = compute_rule_hashes(bundles)

    assert first["semgrep:demo-rule"] == second["semgrep:demo-rule"]
    assert first["semgrep:demo-rule"].startswith("sha256:")
    assert changed["semgrep:demo-rule"] != first["semgrep:demo-rule"]
    resolved = ResolvedRules(rule_hashes=first)
    assert resolved.rule_provenance("semgrep", "demo-rule") == {
        "rule_hash": first["semgrep:demo-rule"],
        "rule_hash_status": "definition_sha256",
    }
    assert resolved.rule_provenance("semgrep", "home.rules.python.demo-rule") == {
        "rule_hash": first["semgrep:demo-rule"],
        "rule_hash_status": "definition_sha256",
    }
    assert resolved.rule_provenance("trivy", "CVE-2026-0001") == {
        "rule_hash": None,
        "rule_hash_status": "unavailable",
    }


def test_gitleaks_rule_hash_and_conflicting_duplicate(tmp_path):
    path = tmp_path / "rules.toml"
    path.write_text('[[rules]]\nid = "secret-rule"\nregex = "first"\n', encoding="utf-8")
    first = compute_rule_hashes([_bundle("gitleaks", path)])
    path.write_text('[[rules]]\nid = "secret-rule"\nregex = "second"\n', encoding="utf-8")
    changed = compute_rule_hashes([_bundle("gitleaks", path)])

    other = tmp_path / "other.toml"
    other.write_text('[[rules]]\nid = "secret-rule"\nregex = "third"\n', encoding="utf-8")
    conflict = compute_rule_hashes([_bundle("gitleaks", path, other)])

    assert first["gitleaks:secret-rule"] != changed["gitleaks:secret-rule"]
    assert conflict["gitleaks:secret-rule"] is None
