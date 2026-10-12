# AppSecGate MCP

Локальный MCP-сервер безопасности для AI-агентов (AppSecGate Phase 1).

Запускает Semgrep, Gitleaks, TruffleHog и Trivy параллельно, нормализует
находки в единый формат `Finding`, ведёт журнал показанного (`shown_findings.db`),
применяет локальные suppression и автофикс, а также двойной контур gates
(warn-only локально, block в CI).

## Разработка

Проект использует [uv](https://docs.astral.sh/uv/) как менеджер пакетов.

```bash
# Из корня репозитория (рекомендуется)
make setup     # установить зависимости (uv sync --extra dev)
make test      # запустить тесты
make lint      # проверка ruff
make format    # форматирование ruff
make check     # lint + test перед коммитом
make clean     # удалить локальные артефакты

# Эквивалентные команды uv из каталога mcp-server/
# uv sync --extra dev
# uv run pytest
# uv run ruff check src tests
# uv run ruff format src tests
```

## Запуск

```bash
# stdio (основной режим)
appsecgate-mcp --transport stdio --project /workspace

# streamable-http (HTTP-демон)
appsecgate-mcp --transport streamable-http --host 0.0.0.0 --port 8765
```

## Режимы транспорта

- `stdio` — основной; агент запускает процесс и общается через stdin/stdout.
- `streamable-http` — долгоживущий HTTP-демон для нескольких клиентов.
  Единая точка входа: `http://<host>:<port>/mcp`.
- `sse` — **устаревший** транспорт (deprecated в MCP spec 2025-03-26).
  Оставлен для обратной совместимости; при запуске печатает `DeprecationWarning`.
  Используйте `streamable-http`.

## Конфигурация

Приоритет: `.appsecgate-mcp/config.yaml` в проекте → `/etc/appsecgate/default.yaml`
в образе → переменные окружения `APPSECGATE_*`.

## Инструменты MCP

`scan_file`, `scan_diff`, `get_config`, `update_config`,
`submit_feedback`, `get_scan_history`, `suppress_finding`.

## Хуки

`session_start`, `pre_tool_use`, `post_tool_use`.
