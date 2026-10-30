"""E2E-харнесс AppSecGate MCP (docs/e2e-test-plan.md).

Пакет заменяет прежний однострочный скрипт ``scripts/e2e_measure.py``
(разбит по AGENTS.md «File Size Limits»):

* ``__main__.py`` — CLI: ``cd scripts && python3 -m e2e_measure ...``;
* ``report.py``   — data-контейнеры отчёта (E2eResult, E2eReport);
* ``client.py``   — MCP-клиент поверх Docker stdio (docker run + ClientSession);
* ``scenarios/``  — сценарии воронки, сессий и T14 (fix-verify, git-diff, память).

Запуск полного цикла:
    python3 -m e2e_measure --project-path /abs/path/to/vuln-project \\
        --other-project-path /abs/path/to/other-project --output e2e-results.json
"""

from __future__ import annotations
