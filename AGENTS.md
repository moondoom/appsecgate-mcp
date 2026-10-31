# AGENTS.md — AppSecGate MCP

## Project
AppSecGate MCP — локальный security scanner для AI-агентов и разработчиков.
Python 3.12+, FastMCP, Pydantic 2.7, SQLite
Сервер находит, хранит, трекает и верифицирует находки.
Фикс генерирует и применяет AI-агент своей LLM — сервер этого НЕ делает.

Полная архитектура: `docs/architecture.md`. Открытые задачи: `docs/open-tasks.md`.
Перед любым изменением — прочитать соответствующий раздел документации.

## Project Map
- `mcp-server/src/` — код MCP-сервера (тулы, хуки, сканеры)
- `appsecgate-master/src/` — центральный (master) сервер, Фаза 2 этап 2
  (ADR-0004/ADR-0006): события/агрегат/аудит и REST API (`api/`); пакет
  `appsecgate-master/`, зависимости — pydantic, FastAPI, uvicorn. MS-4 выполнен.
- `mcp-server/src/appsecgate_mcp/sync/` — edge-синхронизация (MS-3/MS-5,
  ADR-0004 §4.2): `appsecgate-mcp sync` на хосте — экспорт shown_findings.db,
  project-scoped outbox/push и pull CI/global suppressions + master policy в
  data-dir (stdlib urllib). MCP-сервер сеть не вызывает (инвариант №2).
- `mcp-server/src/appsecgate_mcp/server/` — MCP-тулы (`scan_file`, `scan_diff`, `scan_project`,
  `get_fix_context`, `get_fix_context_batch`, `verify_fix`, `verify_fix_batch`,
  `query_findings_db`, `export_snapshot`, `get_config`, `update_config`,
  `submit_feedback`, `get_scan_history`, `suppress_finding`; сессия — `session.py`,
  регистрация тулов — `tools/`, точка входа — `cli.py`). Публичный API реэкспортируется
  из `server.py` (модуль-фасад) — импорты вида `from appsecgate_mcp.server import mcp`
  остаются валидными.
- `mcp-server/src/appsecgate_mcp/scanners/` — обёртки Semgrep, Gitleaks, TruffleHog, Trivy
- `mcp-server/src/appsecgate_mcp/storage/` — SQLite-схема, views; store-классы в
  подмодулях `storage/stores/` (по классу на модуль)
- `mcp-server/tests/` — 482 тестов, все должны быть зелёными
- `config/default.yaml` — дефолтная конфигурация
- `docs/` — архитектура, ADR, открытые задачи, отчёты

## Glossary
- **Finding** — одна находка сканера (rule_id + file + snippet)
- **Fingerprint** — детерминированный ID для сопоставления находок между сканами
- **Suppression** — подавление срабатывания (local / ci / global)
- **Escalation** — переход находки на следующий уровень воронки
- **shown_findings** — журнал находок, показанных разработчику локально
- **Context package** — данные для LLM-агента, НЕ промпт

## Invariants (нарушать нельзя — это ошибка, не warning)
1. Проект монтируется `:ro` — сервер НЕ пишет файлы проекта. Никогда.
2. `network_mode: none` — никаких HTTP-вызовов. Ни в Фазе 1, ни «на будущее».
3. Ноль LLM-вызовов на сервере. Никаких `openai`, `anthropic`, `ollama`,
   `httpx` для LLM. Контекст-пакет — это данные, а не промпт.
4. Redaction секретов ДО записи в БД. Не «при отдаче», а при записи.
5. `query_findings_db` — только `SELECT` по публичным views. Никаких
   `UPDATE`/`DELETE`/`ATTACH`/`PRAGMA`.
6. `project_id` фиксируется при `SessionState.initialize()`. Смена
   `project_path` в одной сессии → ошибка, не warning.

Если задача требует нарушить инвариант — остановиться и спросить.

## Code Conventions
- Python ≥ 3.12, `from __future__ import annotations` в каждом модуле.
- Pydantic v2 (`BaseModel`, `Field(default_factory=...)`).
- `ruff`: line-length 100, select E/F/I/W/UP/B.
- `pytest`: `asyncio_mode=auto`.
- Сканеры запускаются только через `subprocess` без shell (`scanners/runner.py`).
- Store-классы в `storage/stores/` (по классу на модуль), доступ к SQLite
  только через `storage/db.py`.
- Все пути в ответах и fingerprint относительные от корня проекта, с прямыми слэшами.
- Конфиг `update_config` сначала валидируется, потом пишется атомарно (`_atomic_write`), при сбое откатывается.

## Product Principles (неизменны)
- **Warn-only локально.** Блокировка только в CI (Фаза 2).
- **Журнал показанного.** Каждая показанная находка пишется в `shown_findings.db`.
- **Офлайн по умолчанию.** `network.mode: offline`, автодетекта сети нет.
- **Изоляция сканеров.** Каждый сканер — отдельный процесс, без импорта AGPL-кода.
- **Никакого автоопределения языков.** Профили задаются явно в конфиге.
Только три: `mcp`, `pydantic`, `PyYAML`.
Новые production-зависимости запрещены без явного указания.
Dev-зависимости (`pytest`, `ruff`) — не трогать без причины.

## No migration
Продукт не релизился. Миграции не нужны.
Схема SQLite создаётся с нуля в финальном виде.
Если существующие таблицы не соответствуют новой схеме — пересоздаются.

## Build / Test / Format
**Всегда использовать `make`, а не вызывать утилиты напрямую.** Никаких
ручных `docker build -t ...`, `uv run pytest`, `ruff check .` — только
цели из `Makefile`.

| Цель | Что делает | Когда |
|------|-----------|-------|
| `make check` | ruff + pytest для обоих пакетов (mcp-server + appsecgate-master) | перед каждым коммитом |
| `make format` | форматирование ruff (mcp-server) | после изменений |
| `make master-format` | форматирование ruff (appsecgate-master) | после изменений |
| `make master-test` / `master-lint` | тесты / ruff appsecgate-master | при работе над master |
| `make docker-build` | сборка образа `moondoom/appsecgate-mcp:0.1.0` | после коммита |
| `make docker-run` | запуск контейнера с проектом | для отладки |
| `make docker-down` | остановка контейнера | после отладки |

Каноническое имя образа: `moondoom/appsecgate-mcp:0.1.0` (задано в `Makefile`
и `docker-compose.yml`). Ручной `docker build` с неправильным тегом запрещён.

482 тестов mcp-server + 140 тестов appsecgate-master должны оставаться зелёными.
Если тест падает — остановиться, разобраться, НЕ «обновлять тест под код».

## File Size Limits
Ограничения на размер текстовых файлов репозитория (контролируются тестом
`mcp-server/tests/test_file_size_limits.py`, `make check`):

| Категория | Лимит | Исключения |
|-----------|-------|-----------|
| Python (`.py`) | ≤ 400 строк **и** ≤ 20 КБ | — |
| Документация (`.md`/`.html`/`.txt`) | ≤ 500 строк **и** ≤ 40 КБ | `docs/product-vision.md` (исторический артефакт), `docs/architecture.md` (живой справочник) |
| `AGENTS.md` | ≤ 200 строк | — |
| Жёсткий потолок (все текстовые файлы) | ≤ 1500 строк **и** ≤ 60 КБ | — |

Превысил лимит — **разбей на модули**, а не отключай проверку. Исключение можно
добавить только для файла, который нецелесообразно дробить (исторический артефакт,
живой справочник), и только с комментарием-обоснованием в тесте.


## Rules
- Один PR = один этап из роадмапа (см. `docs/open-tasks.md` и `docs/architecture.md` §8).
- Не менять сигнатуры существующих MCP-тулов без явного указания.
- Не удалять таблицы `shown_findings`, `suppressions`, `feedback`.
- Не добавлять поля в `Config` без явного указания — `update_config`
  валидирует схему, лишнее поле сломает валидацию.

## What NOT to do
- Не вызывать `subprocess` с `shell=True`.
- Не писать в `/tmp` файлы > 10 МБ (tmpfs 100M).
- Не логировать промпты или сырые секреты.
- Не «улучшать» схему БД — только пересоздание по `docs/architecture.md`.
- Не рефакторить то, что не просили.
- Не добавлять `try/except` вокруг инвариантов «на всякий случай».

## Workflow: Plan vs Act
- **Plan** — архитектура, разбор спеки, декомпозиция фичи, отладка
  сложного бага (>2 итераций в Act). Не редактирует файлы.
- **Act** — реализация шага плана, правки, тесты, запуск команд.
- Если задача — «добавить тул», «пофиксить тест», «обновить поле» —
  это Act, без Plan.
- Если Act-модель не справилась за 2–3 итерации — переключиться в Plan.
- Архитектурные решения фиксируются в `docs/adr/`, см. `README.md`.

## Definition of Done
Задача завершена, когда:
1. `make check` зелёный.
2. Все 622 теста + новые (если добавлены) проходят.
3. Изменения соответствуют одному этапу роадмапа (`docs/open-tasks.md`).
4. Не нарушен ни один инвариант.
5. Нет новых production-зависимостей.

Если хоть один пункт не выполнен — задача НЕ завершена.

## Common tasks
- **Добавить MCP-тул** → `mcp-server/src/appsecgate_mcp/server/tools/` (`@mcp.tool`),
  тест, обновление README.md (раздел «MCP tools (14)»).
- **Добавить сканер** → `mcp-server/src/scanners/`, обёртка, тест с моком.
- **Пофиксить тест** → сначала понять, ПОЧЕМУ упал. Если код прав —
  тест обновляется. Если тест прав — код фиксится. Не наоборот.
- **Обновить документацию** → README.md / `docs/architecture.md` /
  `docs/open-tasks.md`; архитектурные решения — `docs/adr/`.

## When to stop and ask
- Задача требует нарушить инвариант.
- Тест падает, и непонятно, кто прав — код или тест.
- Задача требует новой production-зависимости.
- Задача выходит за рамки одного этапа роадмапа.
- Неясно, к какому разделу документации относится изменение.
- Открытые задачи проекта — в отдельном файле `docs/open-tasks.md`, не в AGENTS.md.

## Agent File Access (Cline / AI agents)
- Читать содержимое файлов ТОЛЬКО через встроенные тулы агента
  (`read_file`, `list_files`, `search_files`).
- НЕ использовать `bash`/`execute_command` для `cat`, `ls`, `grep`, `find`,
  `head`, `tail`, `wc`, `sed -n`, `awk`, а также конструкций вида
  `ls foo && echo FOUND || echo NOT_FOUND`.
- `execute_command` разрешён только для:
  - целей `make` (`make check`, `make format`, `make docker-*`);
  - git-операций;
  - запуска тестов/линтера — но только через `make`.
- Рабочая директория уже = корень проекта. Пути передавать относительные,
  без префикса `/home/animage/projects/...`.
- Если файл нужно проверить на существование — использовать `list_files`
  или `search_files`, а не `ls ... || echo`.