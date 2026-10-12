"""Тесты лицензионного гварда Rules Bundle (дизайн v1 §1.1, §9)."""

from __future__ import annotations

from appsecgate_mcp.rules.license_guard import LicenseGuard
from appsecgate_mcp.rules.manifest import (
    BundleEntry,
    DistributionMode,
    Redistribution,
    RulesManifest,
)


def _manifest(*bundles: BundleEntry, mode: DistributionMode = DistributionMode.MIT):
    return RulesManifest(version="1.0.0", distribution_mode=mode, bundles=list(bundles))


def _bundle(bundle_id: str, redistribution: Redistribution, license: str = "MIT") -> BundleEntry:
    return BundleEntry(
        id=bundle_id,
        scanner="semgrep",
        path="/opt/appsecgate/rules/x",
        license=license,
        redistribution=redistribution,
    )


def test_mit_allows_allowed_bundles():
    manifest = _manifest(
        _bundle("a", Redistribution.ALLOWED),
        _bundle("b", Redistribution.ALLOWED),
    )
    assert LicenseGuard.check(manifest, DistributionMode.MIT) == []
    assert LicenseGuard.is_compatible(manifest, DistributionMode.MIT)


def test_mit_blocks_restricted():
    manifest = _manifest(
        _bundle("ok", Redistribution.ALLOWED),
        _bundle("bad", Redistribution.RESTRICTED, license="LGPL-3.0 + Commons Clause"),
    )
    errors = LicenseGuard.check(manifest, DistributionMode.MIT)
    assert len(errors) == 1
    assert "bad" in errors[0]
    assert "restricted" in errors[0]
    assert "Commons Clause" in errors[0]
    assert not LicenseGuard.is_compatible(manifest, DistributionMode.MIT)


def test_commercial_allows_restricted():
    manifest = _manifest(_bundle("bad", Redistribution.RESTRICTED))
    assert LicenseGuard.check(manifest, DistributionMode.COMMERCIAL) == []
    assert LicenseGuard.is_compatible(manifest, DistributionMode.COMMERCIAL)


def test_mit_warns_on_internal():
    manifest = _manifest(_bundle("internal", Redistribution.INTERNAL))
    warnings = LicenseGuard.warnings(manifest, DistributionMode.MIT)
    assert len(warnings) == 1
    assert "internal" in warnings[0]
    # internal — не ошибка, сборка не блокируется.
    assert LicenseGuard.check(manifest, DistributionMode.MIT) == []


def test_commercial_no_warnings_for_internal():
    manifest = _manifest(_bundle("internal", Redistribution.INTERNAL))
    assert LicenseGuard.warnings(manifest, DistributionMode.COMMERCIAL) == []


def test_multiple_restricted_reported():
    manifest = _manifest(
        _bundle("r1", Redistribution.RESTRICTED),
        _bundle("r2", Redistribution.RESTRICTED),
    )
    errors = LicenseGuard.check(manifest, DistributionMode.MIT)
    assert len(errors) == 2
