"""Контроль лимитов размера файлов (AGENTS.md «File Size Limits»).

Лимиты:
* Python (`.py`) — ≤ 400 строк **и** ≤ 20 КБ;
* документация (`.md`/`.html`/`.txt`) — ≤ 500 строк **и** ≤ 40 КБ;
  исключения: `docs/product-vision.md` (исторический артефакт),
  `docs/architecture.md` (живой справочник) и все `docs/adr/*.md`
  (ADR-спецификации, дробить нельзя) — до жёсткого потолка;
* `AGENTS.md` — ≤ 500 строк и ≤ 40 КБ (живой справочник для агентов,
  дробить нельзя; с 2026-11-06 действует doc-лимит вместо 200 строк);
* жёсткий потолок для всех текстовых файлов — ≤ 1500 строк **и** ≤ 60 КБ.

Превышение — ошибка: файл нужно разбить на модули, а не ослаблять проверку.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

PY_MAX_LINES = 400
PY_MAX_BYTES = 20 * 1024

DOC_MAX_LINES = 500
DOC_MAX_BYTES = 40 * 1024

HARD_MAX_LINES = 1500
HARD_MAX_BYTES = 60 * 1024

AGENTS_MAX_LINES = 500

# Исключения из лимита документации: файлы, которые нецелесообразно дробить.
DOC_ALLOWLIST = {
    # Исторический артефакт (видение продукта) — не дробится.
    "docs/product-vision.md",
    # Живой справочник по архитектуре — единый документ.
    "docs/architecture.md",
    # Живые ADR-спецификации — разделение нарушит связность решений и обоснований.
    "docs/adr/ADR-0011-scan-run-observability.md",
    "docs/adr/ADR-0012-master-database-and-auth.md",
}

TEXT_EXTENSIONS = {".py", ".md", ".html", ".txt"}


def _tracked_text_files() -> list[Path]:
    """Только существующие tracked-файлы (git ls-files): игнорирует venv/tmp.

    Удалённые, но не застейдженные файлы (индекс устарел) отбрасываются
    проверкой ``is_file()``.
    """
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout
    paths = [REPO_ROOT / line for line in out.splitlines() if Path(line).suffix in TEXT_EXTENSIONS]
    return [path for path in paths if path.is_file()]


def _lines_and_bytes(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    return data.count(b"\n") + 1, len(data)


def test_agents_md_within_doc_limits() -> None:
    # AGENTS.md — живой справочник для агентов: дробить нельзя, действует
    # doc-лимит (500 строк / 40 КБ). Повышен 2026-11-06 после добавления
    # правила «model output is for judgment, not computation».
    lines, size = _lines_and_bytes(REPO_ROOT / "AGENTS.md")
    assert lines <= AGENTS_MAX_LINES, f"AGENTS.md: {lines} строк > {AGENTS_MAX_LINES}"
    assert size <= DOC_MAX_BYTES, f"AGENTS.md: {size} байт > {DOC_MAX_BYTES}"


def test_hard_ceiling_for_all_text_files() -> None:
    offenders = [
        (str(path.relative_to(REPO_ROOT)), lines, size)
        for path in _tracked_text_files()
        for lines, size in [_lines_and_bytes(path)]
        if lines > HARD_MAX_LINES or size > HARD_MAX_BYTES
    ]
    assert not offenders, (
        f"файлы превышают жёсткий потолок ({HARD_MAX_LINES} строк / 60 КБ): {offenders}"
    )


def test_python_files_within_limits() -> None:
    offenders = [
        (str(path.relative_to(REPO_ROOT)), lines, size)
        for path in _tracked_text_files()
        if path.suffix == ".py"
        for lines, size in [_lines_and_bytes(path)]
        if lines > PY_MAX_LINES or size > PY_MAX_BYTES
    ]
    assert not offenders, (
        f"Python-файлы превышают лимит ({PY_MAX_LINES} строк / 20 КБ): {offenders}"
    )


def test_docs_within_limits() -> None:
    offenders = [
        (str(path.relative_to(REPO_ROOT)), lines, size)
        for path in _tracked_text_files()
        if path.suffix in {".md", ".html", ".txt"}
        and path.relative_to(REPO_ROOT).as_posix() not in DOC_ALLOWLIST
        # ADR — живые спецификации решений; дробить нельзя, действует только
        # жёсткий потолок (1500 строк / 60 КБ).
        and not path.relative_to(REPO_ROOT).as_posix().startswith("docs/adr/")
        for lines, size in [_lines_and_bytes(path)]
        if lines > DOC_MAX_LINES or size > DOC_MAX_BYTES
    ]
    assert not offenders, f"документы превышают лимит ({DOC_MAX_LINES} строк / 40 КБ): {offenders}"
