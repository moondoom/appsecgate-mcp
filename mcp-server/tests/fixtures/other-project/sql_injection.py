"""Намеренная SQL-инъекция проекта-полигона (docs/e2e-test-plan.md).

Пример плохой практики: подстановка пользовательского ввода в SQL-запрос.
Semgrep-правила SQL-инъекций должны сработать на этом файле.
"""

from __future__ import annotations

import sqlite3


def get_user_by_id(conn: sqlite3.Connection, user_id: str) -> list:
    """Возвращает пользователя по id — НЕ использовать в продакшене."""
    cursor = conn.execute(f"SELECT * FROM users WHERE id = '{user_id}'")
    return list(cursor.fetchall())
