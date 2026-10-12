"""Адаптер Semgrep — SAST-сканер.

Запускает `semgrep --json` на переданных файлах и парсит результат в
`RawFinding`. Без shell, с таймаутом из `BaseScanner`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from appsecgate_mcp.config.models import ScannerConfig
from appsecgate_mcp.models.finding import Category
from appsecgate_mcp.rules import ResolvedRules
from appsecgate_mcp.scanners.base import BaseScanner, RawFinding
from appsecgate_mcp.scanners.runner import ScannerExecutionError

# Расширения, которые имеет смысл отдавать Semgrep.
_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
        ".java",
        ".kt",
        ".kts",
        ".go",
        ".rb",
        ".php",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".hpp",
        ".cs",
        ".rs",
        ".swift",
        ".scala",
        ".tf",
        ".hcl",
        ".yaml",
        ".yml",
        ".json",
    }
)

# semgrep-core в ряде сборок отдаёт этот плейсхолдер вместо реального кода
# (проверяется через `strings semgrep-core | grep 'requires login'`). Если
# положить его в snippet, fingerprint вырождается в константу, и все находки
# одного правила в одном файле схлопываются в один ID.
_PLACEHOLDER_SNIPPETS: frozenset[str] = frozenset({"requires login"})

# Файлов на один semgrep-процесс. Меньше пакет — меньше риск таймаута на 120 s.
_BATCH_SIZE: int = 100

# Язык профиля → теги бандлов, которые ему соответствуют (дизайн v1 §6.2).
# Фильтрация только явная (из конфига), без автоопределения языков.
_LANG_TAGS: dict[str, set[str]] = {
    "python": {"py", "python"},
    "javascript": {"js", "javascript", "ts", "typescript"},
    "typescript": {"ts", "typescript", "js", "javascript"},
    "java": {"java"},
    "go": {"go"},
    "ruby": {"rb", "ruby"},
    "php": {"php"},
    "c": {"c"},
    "cpp": {"cpp", "c"},
    "csharp": {"csharp", "cs"},
    "rust": {"rust", "rs"},
    "kotlin": {"kotlin", "kt"},
    "scala": {"scala"},
    "swift": {"swift"},
    "hcl": {"iac", "hcl"},
}

# Объединение всех языковых тегов — для отделения языковых бандлов
# от generic/owasp-бандлов, которые не фильтруются по профилю.
_ALL_LANG_TAGS: frozenset[str] = frozenset(
    tag for tags in _LANG_TAGS.values() for tag in tags
)


def _is_placeholder_snippet(text: str) -> bool:
    """True, если сканер вернул заглушку вместо настоящего фрагмента кода."""
    return text.strip().lower() in _PLACEHOLDER_SNIPPETS


class SemgrepAdapter(BaseScanner):
    """Обёртка над Semgrep CLI."""

    name = "semgrep"
    category = Category.SAST
    supported_languages = frozenset(
        {
            "python",
            "javascript",
            "typescript",
            "java",
            "go",
            "ruby",
            "php",
            "c",
            "cpp",
            "csharp",
            "rust",
            "kotlin",
            "scala",
            "swift",
            "hcl",
        }
    )
    default_rulesets: tuple[str, ...] = ("p/security-audit",)

    def __init__(
        self,
        *,
        project_path: str | None = None,
        timeout: float | int = 120,
        config: ScannerConfig | None = None,
        resolved_rules: ResolvedRules | None = None,
    ) -> None:
        super().__init__(
            project_path=project_path,
            timeout=timeout,
            ruleset_hash=resolved_rules.ruleset_hash if resolved_rules else "",
        )
        self.config = config
        self.resolved_rules = resolved_rules

    def _rulesets(self) -> list[str]:
        """Пути правил: resolved-бандлы → config.rulesets → default_rulesets.

        Приоритет отдан локальным путям из Rules Bundle (дизайн v1 §1.5);
        если bundle не разрешился (fail-soft), используется legacy-путь через
        `config.rulesets` (registry-правила вида `p/security-audit`).
        """
        if self.resolved_rules is not None:
            paths = self.resolved_rules.paths_for_scanner(self.name)
            if paths:
                return paths
        if self.config is not None and self.config.rulesets:
            return list(self.config.rulesets)
        return list(self.default_rulesets)

    def _has_profiles(self) -> bool:
        return bool(self.config and self.config.profiles)

    async def is_available(self) -> bool:
        try:
            result = await self.run(["semgrep", "--version"])
        except ScannerExecutionError:
            return False
        return result.returncode == 0

    def _is_supported(self, path: str) -> bool:
        p = Path(path)
        if p.is_dir():
            return True
        return p.suffix.lower() in _SUPPORTED_EXTENSIONS

    async def _select_targets(self, files: list[str], mode: str) -> list[str]:
        if mode == "project":
            return await self._enumerate_project(files)
        return [f for f in files if self._is_supported(f)]

    async def _enumerate_project(self, files: list[str]) -> list[str]:
        """Перечисляет поддерживаемые файлы внутри источника project-режима.

        Источник берётся через `scan_source()`. Исключения задаёт сам проект
        (`.gitignore` через git), без хардкода имён каталогов.
        """
        root = Path(self.scan_source(files, "project"))
        if root.is_file():
            return [str(root)] if self._is_supported(str(root)) else []
        listed = await self._git_listed_files(root)
        if listed is None:
            # Не git-репозиторий: .gitignore недоступен, обходим дерево целиком.
            listed = [str(p) for p in root.rglob("*") if p.is_file()]
        return sorted(
            p for p in listed if Path(p).suffix.lower() in _SUPPORTED_EXTENSIONS
        )

    async def _git_listed_files(self, root: Path) -> list[str] | None:
        """Файлы из git (tracked + untracked, без игнорируемых).

        `--exclude-standard` применяет `.gitignore`, `.git/info/exclude` и
        глобальный ignore. `git -C` задаёт каталог, поэтому пути в выводе
        относительны root. Возвращает None, если root не git-репозиторий.
        """
        cmd = [
            "git",
            "-C",
            str(root),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ]
        try:
            result = await self.run(cmd)
        except ScannerExecutionError:
            return None
        if result.returncode != 0:
            return None
        return [str(root / rel) for rel in result.stdout.split("\0") if rel]

    def _rulesets_for_languages(self, languages: list[str]) -> list[str]:
        """Пути правил, отфильтрованные по языкам профиля (дизайн v1 §6.2).

        Фильтрация — только по тегам бандлов (явная декларация, без
        автоопределения). Бандлы без языковых тегов (generic/owasp) всегда
        включаются. Если теги не совпали ни с чем — безопасный откат к полному
        набору правил (ложный negative хуже ложного positive).
        """
        if self.resolved_rules is None:
            return self._rulesets()
        wanted: set[str] = set()
        for lang in languages:
            wanted |= _LANG_TAGS.get(lang.strip().lower(), set())
        if not wanted:
            return self._rulesets()
        paths: list[str] = []
        for bundle in self.resolved_rules.bundles_for_scanner(self.name):
            lang_tags = {t.lower() for t in bundle.tags} & _ALL_LANG_TAGS
            if not lang_tags or lang_tags & wanted:
                paths.extend(bundle.paths)
        return paths or self._rulesets()

    async def _run_semgrep(self, targets: list[str], rulesets: list[str]) -> list[RawFinding]:
        """Прогоняет targets пакетами: сбой одного пакета не теряет остальные."""
        if not targets or not rulesets:
            return []
        findings: list[RawFinding] = []
        for start in range(0, len(targets), _BATCH_SIZE):
            batch = targets[start : start + _BATCH_SIZE]
            findings.extend(await self._run_batch(batch, rulesets))
        return findings

    async def _run_batch(self, batch: list[str], rulesets: list[str]) -> list[RawFinding]:
        """Один semgrep-процесс на пакет файлов с собственным таймаутом."""
        cmd: list[str] = [
            "semgrep",
            "--json",
            "--quiet",
            "--metrics=off",
            "--disable-version-check",
        ]
        for ruleset in rulesets:
            cmd += ["--config", ruleset]
        cmd += ["--"] + batch

        try:
            result = await self.run(cmd)
        except ScannerExecutionError as exc:
            # Таймаут или отсутствие бинарника: пакет пропущен, скан продолжается.
            self.warnings.append(
                self.redact_project_root(
                    f"semgrep: пакет из {len(batch)} файлов пропущен ({exc})"
                )
            )
            return []
        # Semgrep возвращает 0 (нет находок) или 1 (есть находки). Прочее — ошибка.
        if result.returncode not in (0, 1):
            self.warnings.append(
                f"semgrep: пакет из {len(batch)} файлов завершился с кодом {result.returncode}"
            )
            return []
        return self._parse(result.stdout)

    async def scan(self, files: list[str], mode: str) -> list[RawFinding]:
        self.warnings = []
        targets = await self._select_targets(files, mode)
        if not targets:
            return []
        if self._has_profiles():
            return await self._scan_profiled(targets)
        return await self._run_semgrep(targets, self._rulesets())

    async def _scan_profiled(self, targets: list[str]) -> list[RawFinding]:
        """Сканирует по явным профилям из конфига (декларация, §6.2).

        Каждый профиль получает только файлы под своим `path` и правила,
        отфильтрованные по его языкам. Файлы вне профилей сканируются полным
        набором правил (безопасный дефолт).
        """
        findings: list[RawFinding] = []
        assigned: set[str] = set()
        profiles = self.config.profiles if self.config else []
        for profile in profiles:
            matched = [t for t in targets if self._under_profile(t, profile.path)]
            if not matched:
                continue
            assigned.update(matched)
            rulesets = self._rulesets_for_languages(profile.languages)
            findings.extend(await self._run_semgrep(matched, rulesets))
        rest = [t for t in targets if t not in assigned]
        if rest:
            findings.extend(await self._run_semgrep(rest, self._rulesets()))
        return findings

    def _under_profile(self, target: str, profile_path: str) -> bool:
        """True, если target лежит под директорией профиля."""
        base = Path(profile_path)
        if base in (Path("."), Path("")):
            return True
        target_path = Path(target)
        if not target_path.is_absolute():
            target_path = Path(self.project_path) / target_path
        try:
            return target_path.resolve().is_relative_to(
                (Path(self.project_path) / base).resolve()
            )
        except (OSError, ValueError):
            return False

    def _parse(self, stdout: str) -> list[RawFinding]:
        if not stdout.strip():
            return []
        try:
            data: dict[str, Any] = json.loads(stdout)
        except json.JSONDecodeError:
            return []

        findings: list[RawFinding] = []
        for item in data.get("results", []) or []:
            extra = item.get("extra", {}) or {}
            meta = extra.get("metadata", {}) or {}
            start = item.get("start", {}) or {}
            end = item.get("end", {}) or {}
            file_path = str(item.get("path") or "")
            line_start = int(start.get("line", 1) or 1)
            line_end = int(end.get("line", line_start) or line_start)
            severity = extra.get("severity") or meta.get("severity") or "info"

            # semgrep-core может вернуть плейсхолдер вместо кода — тогда
            # подтягиваем реальные строки из файла, иначе fingerprint выродится.
            raw_lines = extra.get("lines")
            snippet = str(raw_lines) if raw_lines else ""
            if not snippet.strip() or _is_placeholder_snippet(snippet):
                snippet = self._read_snippet(file_path, line_start, line_end)

            scanner_fp = extra.get("fingerprint")
            if not scanner_fp or (
                isinstance(scanner_fp, str) and _is_placeholder_snippet(scanner_fp)
            ):
                scanner_fp = None

            findings.append(
                RawFinding(
                    rule_id=str(item.get("check_id") or "semgrep"),
                    raw_severity=str(severity),
                    file_path=file_path,
                    scanner=self.name,
                    line_start=line_start,
                    line_end=line_end,
                    message=self.redact_project_root(
                        str(extra.get("message") or meta.get("message") or "")
                    ),
                    snippet=snippet,
                    category=Category.SAST,
                    metadata={
                        "fingerprint": scanner_fp,
                        "references": meta.get("references", []),
                        "cwe": meta.get("cwe"),
                        "owasp": meta.get("owasp"),
                        "confidence": meta.get("confidence"),
                    },
                    remediation=meta.get("fix"),
                )
            )
        return findings

    def _read_snippet(self, file_path: str, line_start: int, line_end: int) -> str:
        """Читает реальные строки файла, когда сканер вернул заглушку/пусто.

        Путь может быть относительным — тогда он разрешается от project_path.
        Любые ошибки чтения не должны ронять скан: возвращаем пустую строку.
        """
        if not file_path:
            return ""
        path = Path(file_path)
        if not path.is_absolute():
            path = Path(self.project_path) / path
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        lines = text.splitlines()
        if not lines:
            return ""
        start = max(line_start, 1)
        end = min(line_end, len(lines))
        if start > len(lines):
            return ""
        return "\n".join(lines[start - 1 : end])
