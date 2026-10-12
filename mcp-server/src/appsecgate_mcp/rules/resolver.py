"""RuleResolver — превращает Rules Bundle в конкретные пути на диске.

Слой между `ConfigLoader` и `ScannerRegistry`. Разрешает логические бандлы
из `manifest.yaml` в реальные пути с учётом overlay-слоёв (default → project
→ user), считает инвентаризационный `ruleset_hash` и собирает overlay-настройки
(`disable`/`replace`) без deep-merge. См. дизайн v1 §1.5, §3.1, §3.3.

Правила слияния (без deep-merge):
  * файл с тем же относительным именем в верхнем слое **заменяет** нижний;
  * новые файлы/директории — добавляются;
  * `disable`/`replace` из overlay-манифестов аккумулируются (верхний слой
    переопределяет `replace` и дополняет `disable`).

Fail-soft: невалидный overlay пропускается с warning, дефолт сохраняется.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, Field

from appsecgate_mcp.rules.manifest import (
    BundleEntry,
    DistributionMode,
    Redistribution,
    RulesManifest,
    load_manifest_soft,
)

# Расположение overlay-слоёв правил.
DEFAULT_RULES_ROOT = Path("/opt/appsecgate/rules")
PROJECT_RULES_REL = Path(".appsecgate-mcp") / "rules"
USER_RULES_REL = Path(".appsecgate-mcp") / "rules"
MANIFEST_NAME = "manifest.yaml"

# Сканеры, для которых резолвим правила.
_SCANNERS: tuple[str, ...] = ("semgrep", "gitleaks", "trufflehog", "trivy")

# Расширения файлов правил, которые учитываем при разрешении/хэшировании.
_RULE_SUFFIXES: frozenset[str] = frozenset({".yaml", ".yml", ".toml"})


def _file_sha256(path: str | Path) -> str:
    """Возвращает sha256-хэш содержимого файла (hex)."""
    digest = hashlib.sha256()
    digest.update(Path(path).read_bytes())
    return digest.hexdigest()


def compute_ruleset_hash(
    version: str,
    file_paths: list[str],
    scanner_version: str,
    distribution_mode: DistributionMode,
    licenses: list[str] | None = None,
) -> str:
    """Инвентаризационный хэш набора правил (дизайн v1 §1.5).

    `sha256(version + sorted(file_sha256) + scanner_version + distribution_mode
    + sorted(licenses))`. Лицензии учитываются, чтобы смена лицензионного
    состава бандлов меняла хэш даже при тех же файлах.
    """
    lines: list[str] = [version, scanner_version, distribution_mode.value]
    lines.extend(f"license:{lic}" for lic in sorted(set(licenses or [])))
    for path in sorted(file_paths):
        try:
            lines.append(_file_sha256(path))
        except OSError:
            lines.append(f"missing:{path}")
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _collect_rule_files(source: Path) -> dict[str, Path]:
    """Собирает файлы правил под `source`, ключ — путь относительно `source`.

    Директория рекурсивно обходится; поддерживаются только расширения из
    `_RULE_SUFFIXES`. Для одиночного файла ключ — его имя.
    """
    if source.is_dir():
        result: dict[str, Path] = {}
        for path in sorted(source.rglob("*")):
            if path.is_file() and path.suffix.lower() in _RULE_SUFFIXES:
                result[str(path.relative_to(source))] = path
        return result
    if source.is_file() and source.suffix.lower() in _RULE_SUFFIXES:
        return {source.name: source}
    return {}


class ResolvedBundle(BaseModel):
    """Бандл после разрешения overlay-слоёв."""

    id: str
    scanner: str
    path: str  # исходный путь из манифеста (для отображения)
    license: str = ""
    source: str = ""
    redistribution: Redistribution = Redistribution.ALLOWED
    tags: list[str] = Field(default_factory=list)
    # Аргументы путей для сканера: либо [директория], либо список файлов.
    paths: list[str] = Field(default_factory=list)
    # Все файлы правил (для подсчёта и хэширования).
    files: list[str] = Field(default_factory=list)

    @property
    def rules_count(self) -> int:
        """Число файлов правил в бандле."""
        return len(self.files)


class ResolvedRules(BaseModel):
    """Результат разрешения правил: пути, бандлы, overlay'и, хэш, warnings."""

    version: str = "0.0.0"
    distribution_mode: DistributionMode = DistributionMode.MIT
    ruleset_hash: str = ""
    bundles: list[ResolvedBundle] = Field(default_factory=list)
    # scanner -> список выключенных rule-id
    disable: dict[str, list[str]] = Field(default_factory=dict)
    # scanner -> {rule-id: путь к файлу-замене}
    replace: dict[str, dict[str, str]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    def bundles_for_scanner(self, scanner: str) -> list[ResolvedBundle]:
        """Бандлы указанного сканера."""
        name = scanner.lower()
        return [b for b in self.bundles if b.scanner.lower() == name]

    def paths_for_scanner(self, scanner: str) -> list[str]:
        """Пути аргументов сканера, агрегированные по его бандлам."""
        result: list[str] = []
        for bundle in self.bundles_for_scanner(scanner):
            result.extend(bundle.paths)
        return result

    def disable_for_scanner(self, scanner: str) -> list[str]:
        """Выключенные rule-id для сканера."""
        return list(self.disable.get(scanner.lower(), []))

    def bundles_summary(self) -> list[dict[str, object]]:
        """Компактная сводка бандлов для meta (id + rules_count)."""
        return [{"id": b.id, "rules_count": b.rules_count} for b in self.bundles]


class RuleResolver:
    """Разрешает Rules Bundle с учётом overlay-слоёв.

    Слои (от низшего к высшему приоритету): default (`default_root`),
    project (`project_root`), user (`user_root`).
    """

    def __init__(
        self,
        *,
        default_root: str | Path = DEFAULT_RULES_ROOT,
        project_root: str | Path | None = None,
        user_root: str | Path | None = None,
    ) -> None:
        self.default_root = Path(default_root)
        self.project_root = Path(project_root) if project_root else None
        self.user_root = Path(user_root) if user_root else None

    # ------------------------------------------------------------------
    # Фабрики
    # ------------------------------------------------------------------
    @classmethod
    def from_config(cls, config: object) -> RuleResolver:
        """Собирает резолвер из объекта конфига (best-effort по атрибутам).

        Использует `rules_path`/`project_path` если они есть, иначе дефолты.
        Интеграция в `ConfigLoader` — этап 2 плана.
        """
        default_root = getattr(config, "rules_path", None) or DEFAULT_RULES_ROOT
        project_path = getattr(config, "project_path", None)
        project_root = Path(project_path) / PROJECT_RULES_REL if project_path else None
        user_root = Path.home() / USER_RULES_REL
        return cls(
            default_root=default_root,
            project_root=project_root,
            user_root=user_root,
        )

    # ------------------------------------------------------------------
    # Разрешение
    # ------------------------------------------------------------------
    def resolve(
        self,
        *,
        distribution_mode: DistributionMode | None = None,
        scanner_version: str = "",
    ) -> ResolvedRules:
        """Разрешает бандлы, overlay'и и считает `ruleset_hash`.

        Fail-soft: битый overlay пропускается с warning; отсутствующий бандл
        не роняет разрешение, а отмечается в warnings. Возвращает всегда
        `ResolvedRules` (возможно пустой).
        """
        warnings: list[str] = []
        manifests = self._load_manifests(warnings)
        default_manifest = manifests[0] if manifests else None

        mode = distribution_mode or (
            default_manifest.distribution_mode if default_manifest else DistributionMode.MIT
        )
        version = default_manifest.version if default_manifest else "0.0.0"

        merged_bundles = self._merge_bundles(manifests)
        bundles: list[ResolvedBundle] = []
        all_files: list[str] = []
        for bundle in merged_bundles.values():
            resolved = self._resolve_bundle(bundle, warnings)
            if resolved is None:
                continue
            bundles.append(resolved)
            all_files.extend(resolved.files)

        disable, replace = self._merge_overrides(manifests)

        licenses = [b.license for b in bundles if b.license]
        ruleset_hash = compute_ruleset_hash(
            version, all_files, scanner_version, mode, licenses=licenses
        )
        return ResolvedRules(
            version=version,
            distribution_mode=mode,
            ruleset_hash=ruleset_hash,
            bundles=bundles,
            disable=disable,
            replace=replace,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Внутренние шаги
    # ------------------------------------------------------------------
    def _load_manifests(self, warnings: list[str]) -> list[RulesManifest]:
        """Загружает default-манифест и overlay-манифесты (fail-soft)."""
        manifests: list[RulesManifest] = []
        default_manifest, warning = load_manifest_soft(self.default_root / MANIFEST_NAME)
        if warning:
            warnings.append(f"rules default manifest ignored: {warning}")
        if default_manifest is not None:
            manifests.append(default_manifest)

        for label, root in (("project", self.project_root), ("user", self.user_root)):
            if root is None:
                continue
            manifest_path = Path(root) / MANIFEST_NAME
            # Отсутствующий overlay — норма (overlay опционален), не warning.
            if not manifest_path.exists():
                continue
            manifest, warning = load_manifest_soft(manifest_path)
            if warning:
                warnings.append(f"rules {label} overlay ignored: {warning}")
                continue
            if manifest is not None:
                manifests.append(manifest)
        return manifests

    @staticmethod
    def _merge_bundles(manifests: list[RulesManifest]) -> dict[str, BundleEntry]:
        """Сливает бандлы по id: верхний слой переопределяет целиком."""
        merged: dict[str, BundleEntry] = {}
        for manifest in manifests:
            for bundle in manifest.bundles:
                merged[bundle.id] = bundle
        return merged

    def _resolve_bundle(self, bundle: BundleEntry, warnings: list[str]) -> ResolvedBundle | None:
        """Разрешает один бандл по overlay-слоям.

        Возвращает `None`, если ни один слой не дал файлов на диске.
        """
        rel_key = self._rel_key(bundle)
        sources: list[Path] = []

        default_path = Path(bundle.path)
        if default_path.exists():
            sources.append(default_path)
        for root in (self.project_root, self.user_root):
            if root is None:
                continue
            candidate = Path(root) / rel_key
            if candidate.exists() and candidate not in sources:
                sources.append(candidate)

        if not sources:
            warnings.append(f"rules bundle '{bundle.id}' not found on disk: {bundle.path}")
            return None

        # Файлы для хэша/подсчёта — всегда с учётом всех слоёв.
        merged_files: dict[str, Path] = {}
        for source in sources:
            merged_files.update(_collect_rule_files(source))
        files = sorted(str(path) for path in merged_files.values())

        # Аргументы сканера: одиночная директория → отдаём её целиком,
        # иначе — список файлов (замена по имени уже применена слиянием).
        if len(sources) == 1 and sources[0].is_dir():
            paths = [str(sources[0])]
        else:
            paths = files

        return ResolvedBundle(
            id=bundle.id,
            scanner=bundle.scanner,
            path=str(default_path),
            license=bundle.license,
            source=bundle.source,
            redistribution=bundle.redistribution,
            tags=list(bundle.tags),
            paths=paths,
            files=files,
        )

    def _rel_key(self, bundle: BundleEntry) -> str:
        """Относительный ключ бандла (для поиска в overlay-слоях)."""
        path = Path(bundle.path)
        try:
            return str(path.relative_to(self.default_root))
        except ValueError:
            return path.name

    @staticmethod
    def _expand(path: str) -> str:
        """Раскрывает `~` и делает путь абсолютным (для `replace`)."""
        return str(Path(path).expanduser())

    def _merge_overrides(
        self, manifests: list[RulesManifest]
    ) -> tuple[dict[str, list[str]], dict[str, dict[str, str]]]:
        """Аккумулирует `disable`/`replace` из всех манифестов (слоёв)."""
        disable: dict[str, list[str]] = {scanner: [] for scanner in _SCANNERS}
        replace: dict[str, dict[str, str]] = {scanner: {} for scanner in _SCANNERS}
        for manifest in manifests:
            if manifest.overrides is None:
                continue
            for scanner in _SCANNERS:
                overrides = manifest.overrides.for_scanner(scanner)
                for rule_id in overrides.disable:
                    if rule_id not in disable[scanner]:
                        disable[scanner].append(rule_id)
                for rule_id, target in overrides.replace.items():
                    replace[scanner][rule_id] = self._expand(target)
        return disable, replace
