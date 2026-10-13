# Scan Diagnostics — найденные проблемы (открытые гипотезы)

> **Назначение:** журнал слабых мест в производительности и прозрачности
> сканирования. Заполняется по итогам прогона `appsecgate-mcp diagnose` /
> логирования (`--log-level`/`--log-file`). Используется на следующем прогоне:
> каждая строка либо подтверждается, либо отклоняется, либо переходит в PR.

**Статусы:** `открыто` — гипотеза не проверена замером; `подтверждено` —
воспроизведено логами; `отклонено` — замерами не подтвердилось.

---

## Как диагностировать

```bash
# Логи в файл (ротация 2 МБ x 3), уровень INFO/DEBUG
cd mcp-server && uv run appsecgate-mcp --log-level DEBUG --log-file /tmp/appsecgate.log
# или только stderr
cd mcp-server && uv run appsecgate-mcp --log-level INFO
```

В логах фиксируется каждый запуск внешней команды: `argv` (с редакцией корня
проекта), `returncode`, `duration_ms`, размеры `stdout`/`stderr`, исход
(`ok` / `nonzero_exit` / `timeout` / `not_found`), а также этапы скана и
инициализации сессии. Секреты и содержимое `stdout` в логи не попадают.

Ключевые строки для поиска по логу:

- `spawn ... duration_ms= ... returncode= ... cmd=...` — время и исход каждого бинарника.
- `scan start mode= ... files= ...` / `scan done ... duration_ms= ...` — этапы скана.
- `tool= ... duration_ms= ...` — время каждого MCP-тула.
- `session init project_id= ...` / `trivy db seed done seeded= ...` — старт сессии.

---

## Гипотезы (кандидаты на слабые места)

| # | Гипотеза | Где в коде | Как подтвердить | Статус |
|---|---|---|---|---|
| 1 | `scan_file`/`diff` гоняет gitleaks/trufflehog/trivy по всему корню проекта, а не по переданным файлам | `scanners/base.py:103-117` (`scan_source`) | время `scan_file` одного файла vs число файлов в проекте | открыто |
| 2 | Пакеты Semgrep (по 100 файлов) запускаются последовательно | `scanners/semgrep.py:_run_semgrep` | `duration_ms` по пакетам в DEBUG-логе | открыто |
| 3 | Вне git-репозитория `rglob("*")` обходит `.venv`, `node_modules` и т.п. | `scanners/semgrep.py:_enumerate_project` | число целей из `_enumerate_project` | открыто |
| 4 | Онлайн-синхронизация Trivy DB на `session_start` задерживает первый вызов | `server.py:_sync_trivy_db` | `trivy db sync online timeout=...` и время инициализации | открыто |
| 5 | Таймаут 120 с захардкожен, в конфиге/настройках не меняется | `scanners/registry.py:from_config`, `server.py` | строка `spawn timeout ... cmd=...` | открыто |
| 6 | Адаптеры при ненулевом коде возвращают `[]` молча, без причины | `gitleaks.py`, `trivy.py`, `trufflehog.py` | `nonzero_exit` + `stderr tail` в логе | открыто |
| 7 | `scan_project` (announce) не отдаёт `meta`: сканеры, ошибки, время | `server.py:_build_announce_output` | сравнение ответа `scan_project` и `scan_file` | открыто |
| 8 | `duration_ms` не охватывает `session_start`, запись в БД, сборку ответа | `orchestration/coordinator.py`, `server.py` | сумма этапов vs реальное время тула | открыто |
| 9 | `is_available()` запускает `--version` каждого сканера на каждый скан | `orchestration/coordinator.py:_select_available` | число `cmd=... --version` в логе | открыто |
| 10 | Конфигурация отладки в `.vscode/launch.json` ссылается на несуществующий `src/diag_mcp.py` | `.vscode/launch.json` | `ls src/diag_mcp.py` (пусто) | открыто |

---

## Как фиксировать результат прогона

1. Запустить скан с `--log-level DEBUG --log-file /tmp/appsecgate.log`, воспроизведя
   медленный/падающий сценарий.
2. Для каждой строки таблицы найти соответствующие строки в логе.
3. Проставить статус `подтверждено` (с замерами) или `отклонено`.
4. Подтверждённые пункты, требующие изменения кода, выносятся отдельным PR
   (один PR — один этап роадмапа, AGENTS.md §8).

---

## Уже сделанное (инструментарий)

- Модуль `src/appsecgate_mcp/logging_setup.py`: `configure_logging(level, log_file)`.
- Логирование запуска команд в `scanners/runner.py` (argv/returncode/duration/stderr tail с редакцией).
- Замеры этапов в `orchestration/coordinator.py` и инициализации/Trivy DB в `server.py`.
- Обёртка `_log_tool` в `server.py` для имени/длительности/размера ответа каждого MCP-тула.
- Флаги `--log-level`/`--log-file` в `server.main()` и `hooks.hook_main()`.
- Тесты: `tests/test_logging.py`.