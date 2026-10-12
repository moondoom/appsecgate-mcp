"""Вычисление стабильного ``logical_id`` находки (arch §4.8).

``logical_id`` переживает смену fingerprint: при сдвигах строк в пределах
±20 он остаётся прежним, потому что опирается на AST-scope (Python) или
bucket по строкам (остальные языки), а не на номер конкретной строки.

Формула (списка §4.8):

    scope_key = extract_scope_key(source, line_start) or f"L{line_start // 20}"
    logical_id = sha256(f"{rule_id}:{file_path}:{scope_key}").hexdigest()[:16]
"""

from __future__ import annotations

import ast
import hashlib

_BUCKET_SIZE = 20


def extract_scope_key(source: str, line: int) -> str | None:
    """Qualified name охватывающего символа в Python-файле.

    Возвращает, например, ``module.top.inner`` — имя функции/класса, в теле
    которого находится ``line`` (1-based). Для не-Python или при ошибке
    парсинга возвращает ``None`` (fallback на bucket по строкам).
    """
    if not source:
        return None
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None

    matches: list[tuple[int, str]] = []

    def _valid(node: ast.AST) -> bool:
        return getattr(node, "lineno", None) is not None

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
            start = node.lineno
            end = getattr(node, "end_lineno", None) or start
            if _valid(node) and start <= line <= end:
                matches.append((end - start, name))
        elif isinstance(node, ast.Lambda):
            # Лямбды не имеют имени, но добавляют анонимный scope.
            start = getattr(node, "lineno", None)
            end = getattr(node, "end_lineno", None)
            if start is not None and end is not None and start <= line <= end:
                matches.append((end - start, "<lambda>"))

    if not matches:
        return None
    # Самый вложенный (наименьший диапазон) — ближайший охватывающий символ.
    matches.sort(key=lambda item: item[0])
    return matches[0][1]


def compute_logical_id(rule_id: str, file_path: str, line_start: int, source: str) -> str:
    """16-символьный стабильный id находки (списка §4.8)."""
    scope_key = extract_scope_key(source, line_start) or f"L{line_start // _BUCKET_SIZE}"
    key = f"{rule_id}:{file_path}:{scope_key}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


__all__ = ["compute_logical_id", "extract_scope_key"]
