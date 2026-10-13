"""Намеренный XSS проекта-полигона (docs/e2e-test-plan.md).

Пример плохой практики: вывод пользовательского ввода без экранирования.
Semgrep-правила XSS должны сработать на этом файле.
"""

from __future__ import annotations

from flask import Flask, request

app = Flask(__name__)


@app.route("/profile")
def profile() -> str:
    """Отдаёт <name> без экранирования — НЕ использовать в продакшене."""
    name = request.args.get("name", "")
    return f"<div class='profile'>{name}</div>"
