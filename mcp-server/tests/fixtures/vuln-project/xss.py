"""Намеренный XSS проекта-полигона (docs/e2e-test-plan.md).

Пример плохой практики: Jinja2-окружение без autoescape. Пользовательский
ввод рендерится без экранирования → XSS (CWE-116, OWASP A7:2017).
Semgrep-правило python/escaping/rule-jinja2-autoescape-false должно
сработать на этом файле.
"""

from __future__ import annotations

import jinja2

# autoescape выключен — вывод пользовательского ввода в HTML без экранирования.
env = jinja2.Environment(autoescape=False)
