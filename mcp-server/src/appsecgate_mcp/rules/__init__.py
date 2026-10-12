"""Rules Bundle: манифест, резолвер путей и лицензионный гвард.

Слой между `ConfigLoader` и `ScannerRegistry`: превращает логические ID
правил из config.yaml в конкретные пути на диске (с учётом overlay-слоёв)
и обеспечивает лицензионную чистоту поставки.
"""

from appsecgate_mcp.rules.license_guard import LicenseGuard
from appsecgate_mcp.rules.manifest import (
    BundleEntry,
    DistributionMode,
    ManifestError,
    Overrides,
    Redistribution,
    RulesManifest,
    ScannerOverrides,
    load_manifest,
    load_manifest_soft,
)
from appsecgate_mcp.rules.resolver import (
    ResolvedBundle,
    ResolvedRules,
    RuleResolver,
    compute_ruleset_hash,
)
from appsecgate_mcp.rules.trivy_db import (
    TrivyDbStatus,
    seed_trivy_db,
    sync_trivy_db,
    trivy_db_status,
)

__all__ = [
    "BundleEntry",
    "DistributionMode",
    "LicenseGuard",
    "ManifestError",
    "Overrides",
    "Redistribution",
    "ResolvedBundle",
    "ResolvedRules",
    "RuleResolver",
    "RulesManifest",
    "ScannerOverrides",
    "TrivyDbStatus",
    "compute_ruleset_hash",
    "load_manifest",
    "load_manifest_soft",
    "seed_trivy_db",
    "sync_trivy_db",
    "trivy_db_status",
]
