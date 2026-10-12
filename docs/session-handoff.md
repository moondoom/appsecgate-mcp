# Session handoff: AppSecGate MCP

> **Назначение:** стартовая точка для новой сессии. Актуально на момент последнего коммита `08cb782`.

---

## 1. Состояние проекта

**Фаза 1 (локальный MCP-сервер) реализована:**
- 12 MCP-инструментов: `scan_file`, `scan_diff`, `scan_project`, `get_fix_context`, `get_fix_context_batch`, `query_findings_db`, `export_snapshot`, `get_config`, `update_config`, `submit_feedback`, `get_scan_history`, `suppress_finding` (`auto_fix` удалён — см. fix-workflow-design §4.2).
- Хуки `session_start`, `pre_tool_use`, `post_tool_use` вынесены из MCP в CLI: `appsecgate-mcp hook <name>` (JSON из stdin, JSON в stdout).
- Сканеры: Semgrep, Gitleaks, TruffleHog, Trivy.
- Rules bundle (`mcp-server/rules/`) с `LicenseGuard` и `RuleResolver`.
- Хранилище: `shown_findings.db`, `feedback.db`, `scan_cache.db` (SQLite).
- Dockerfile и `docker-compose.yml` в `mcp-server/`.
- Тесты: 186 passed. Линт: `ruff` чистый.

**Гигиена выполнена (последние коммиты):**
- `7763d18` удалён `docs/mcp-stabilization-plan.md`.
- `9e9d9f5` исправлен `TAG` в `Makefile`, добавлена цель `test-file`.
- `ddeac61` `_reinitialize` в `update_config`, `OrderedDict` в реестре находок.
- `08cb782` удалён `docs/rules-implementation-plan.md`.

**Удалено, но не закоммичено:** `docs/session-handoff.md` (старая версия). Новая версия создаётся этим файлом.

---

## 2. Структура

```
appsecgate-mcp/
├── Makefile                  # setup, test, test-file, lint, format, check, docker-*
├── docs/
│   ├── architecture.md       # архитектура и лицензионная модель
│   ├── product-vision.md     # продукт и фазы
│   ├── publish_plan.md       # публикация в Docker Hub
│   └── session-handoff.md    # этот файл
└── mcp-server/
    ├── pyproject.toml, uv.lock, Dockerfile, docker-compose.yml
    ├── rules/                # bundle правил, manifest.yaml, THIRD_PARTY_NOTICES.md
    ├── scripts/entrypoint.sh
    ├── src/appsecgate_mcp/
    │   ├── server.py         # FastMCP, SessionState, 9 инструментов
    │   ├── hooks.py          # хуки и CLI
    │   ├── git.py
    │   ├── config/           # loader, models
    │   ├── scanners/         # base, registry, runner, semgrep, gitleaks, trufflehog, trivy
    │   ├── orchestration/    # coordinator, autofixer, gate
    │   ├── normalization/    # normalizer, fingerprint, dedup
    │   ├── models/           # finding
    │   ├── rules/            # manifest, resolver, license_guard, trivy_db
    │   └── storage/          # db, stores
    └── tests/                # 186 тестов
```

---

## 3. Команды

Из корня репозитория:

```bash
make setup        # uv sync --extra dev
make check        # lint + test
make test-file FILE=tests/test_server_smoke.py
make format
make docker-build
make docker-run
```

---

## 4. Конвенции

- Python ≥ 3.11, `from __future__ import annotations` в каждом модуле.
- Pydantic v2 (`BaseModel`, `Field(default_factory=...)`).
- Докстринги на русском.
- `ruff`: line-length 100, select E/F/I/W/UP/B.
- `pytest`: `asyncio_mode=auto`.
- Сканеры запускаются только через `subprocess` без shell (`scanners/runner.py`).
- Store-классы в `storage/stores.py`, доступ к SQLite только через `storage/db.py`.
- Новые пакеты экспортируются через `__init__.py` с `__all__`.
- Все пути в ответах и fingerprint относительные от корня проекта, с прямыми слэшами.
- Путь вне проекта — ошибка, а не молчаливое сканирование.
- Конфиг `update_config` сначала валидируется, потом пишется атомарно (`_atomic_write`), при сбое откатывается.

---

## 5. Принципы продукта (неизменны)

- **Warn-only локально.** Блокировка только в CI (Фаза 2).
- **Журнал показанного.** Каждая показанная находка пишется в `shown_findings.db`.
- **Офлайн по умолчанию.** `network.mode: offline`, автодетекта сети нет.
- **Изоляция сканеров.** Каждый сканер — отдельный процесс, без импорта AGPL-кода.
- **Никакого автоопределения языков.** Профили задаются явно в конфиге.

---

## 6. Открытые вопросы

**Из спеки rules bundle (`architecture.md`, §11 старого плана):**
1. Список правил `opengrep-sast-rules`, исключённых из-за Commons Clause (закрыт частично: `jetbrains/` исключён).
2. Схема custom-detectors TruffleHog 3.82.
3. Реальный размер `trivy-db-seed` на amd64.
4. `--network=none` для sync или отдельная команда.
5. Автогенерация `THIRD_PARTY_NOTICES.md` (Syft/Grype).
6. Юридическая проверка изоляции `subprocess` для AGPL.

**Из архитектуры:**
- Спайк fingerprint: нормализованный сниппет может схлопывать разные находки.
- TruffleHog: запускать вместе с Gitleaks или только на diff.
- Semgrep: `--baseline` или собственная фильтрация.
- LLM для `auto_fix suggestion`: vLLM, YandexGPT или Ollama.
- Синхронизация `shown_findings.db` с master при конфликтах.

**Документация:**
- `docs/roadmap.md` и `docs/api/openapi.yaml` упоминаются в README и vision, но не созданы. Оставлено осознанно.

---

## 7. Отложено

- **Этап 8 (CI-валидация bundle):** GitHub Actions с `semgrep --validate/--test`, LicenseGuard, сборкой образа. Откладывается до проработки функционала.
- **Этап 6 старого стабилизационного плана (регрессия и приёмка):** не начат, план удалён. При необходимости завести короткий чеклист заново.
- **Публикация в Docker Hub и CI на GitHub Actions:** по `docs/publish_plan.md`, не начато.

---

## 8. С чего начать следующую сессию

1. Прочитать этот файл и `docs/product-vision.md` (раздел «Фаза 1»).
2. Проверить `git status` и `make check`.
3. Выбрать функциональный блок для проработки. Кандидаты из открытых вопросов: fingerprint-спайк, `auto_fix` через `suggestion`, TruffleHog-стратегия.