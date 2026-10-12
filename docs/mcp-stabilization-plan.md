# План реализации: Вариант A. Стабилизация Фазы 1 (MCP-сервер)

> **Статус:** черновик, ожидает ревизии.
> **Связанные документы:** [`docs/rules-implementation-plan.md`](rules-implementation-plan.md) (Rules Bundle, отдельный трек).

**Цель:** закрыть проблемы безопасности и корректности в `mcp-server/` до расширения функционала.
**Срок:** 2–3 недели.

Перед правками нужно прочитать `config/loader.py`, `scanners/runner.py`, `orchestration/coordinator.py` и `tests/test_server_smoke.py`. Без этого нельзя точно оценить, как пути попадают в сканеры и что уже покрыто тестами.

---

## Решения и расхождения с кодом (ревизия 2026-10-12)

**Подтверждённые решения:**

| # | Вопрос | Решение |
|---|--------|---------|
| 1 | Точка нормализации путей (этап 1a) | `ScanCoordinator._to_finding` до расчёта fingerprint, а не `normalization/normalizer.py` (там только severity и пороги). Отклонение от плана. |
| 2 | Путь вне проекта | Ошибка (`{"error": ...}` или `status: error`), а не молчаливое сканирование и не обрезание пути. |
| 3 | Валидация `update_config` (этап 3) | Собрать `deep_merge(default, existing, updates)` и проверить через `Config.model_validate`, как в `ConfigLoader.load`. Запись только после успешной проверки. |
| 4 | Миграция `shown_findings.db` и `feedback.db` | Вынесена в отдельный открытый вопрос (см. раздел «Открытые вопросы»). Не решена. |
| 5 | Правка `test_extract_touched_files` | Согласована. Тест переписан на путь внутри временного проекта. |

**Расхождения имён и структуры (план → код):**

| Имя в плане | Фактическое состояние в коде | Действие |
|-------------|------------------------------|----------|
| `_resolve_inside_project` | Создан на этапе 1 | закрыто |
| `_initialize_locked` | Отсутствует | создать на этапе 2 |
| `_atomic_write` | Отсутствует | создать на этапе 3 |
| `hooks.py` | Отсутствует, hooks — `@mcp.tool()` в `server.py` | создать на этапе 4 |
| `_relpath` | Существовал как преобразование только входных путей, без границ проекта; на этапе 1 больше не используется в путях входа | удалить на этапе 1a или 1 (решить при правке) |
| `normalization/normalizer.py` как точка нормализации путей | Содержит только severity и пороги | заменено на `coordinator._to_finding` (решение 1) |
| `ConfigLoader.load_config_file` | Есть, вызывает `Config.model_validate` | использовать на этапе 3 |
| Количество инструментов в `list_tools()` | 12 (включая `session_start`, `pre_tool_use`, `post_tool_use`), по плану должно быть 9 | исправить на этапе 4 |

**Прочие факты, выявленные при сверке:**

- `scan_file` до этапа 1 пропускал абсолютный путь вне проекта, если файл существовал.
- `scan_project` до этапа 1 не проверял границы после `resolve()`.
- `Finding.file_path` документирован как относительный путь, но ничем не гарантируется. Сейчас путь от сканеров попадает в `RawFinding.file_path` без нормализации.
- Baseline тестов: 121 (до этапа 1), 129 (после этапа 1).

---

## Этап 1. Защита путей (path traversal)

**Проблема:** `scan_file` и `scan_project` принимают абсолютные пути и `../`, не проверяя, что цель находится внутри `project_path`. `_extract_touched_files` в `post_tool_use` тоже не проверяет границы проекта.

**Действия:**
1. Добавить в `server.py` единый хелпер, который разрешает путь и проверяет вхождение в корень проекта.
2. Использовать его во всех точках, принимающих путь: `scan_file`, `scan_project`, `_extract_touched_files`.
3. Пути за пределами проекта возвращать как ошибку, а не молча сканировать.
4. Проверить симлинки: `resolve()` раскрывает их, поэтому симлинк, ведущий наружу, будет отклонён.

```python
# mcp-server/src/appsecgate_mcp/server.py
def _resolve_inside_project(path: str, project: str) -> Path:
    base = Path(project).resolve()
    candidate = Path(path) if Path(path).is_absolute() else base / path
    resolved = candidate.resolve()
    if not resolved.is_relative_to(base):
        raise ValueError(f"path outside project: {path}")
    return resolved
```

**Тесты:** `tests/test_path_guard.py`. Абсолютный путь вне проекта, `../../etc/passwd`, симлинк наружу, путь внутри проекта, пустая строка.

---

## Этап 1a. Относительные пути в находках

**Проблема:** при сканировании в Docker проект смонтирован в `/workspace`, и сканеры возвращают абсолютные пути вида `/workspace/src/app.py`. Агент получает эти пути в `findings[].file_path`, `meta.scanned_files`, `autofixes[].file_path`, `files` (ответ `post_tool_use`) и в тексте `reason`/`message`. Агент не может сопоставить их с путями из своего рабочего каталога и начинает путать файлы. В ответах `_relpath` применяется только к входным аргументам, а не к результатам сканеров. Кроме того, абсолютный путь попадает в fingerprint, поэтому одна и та же находка получает разные `finding_id` при локальном запуске, в Docker и в CI.

**Инвариант:** во всех ответах MCP, в `ScanResult`, `Finding`, fingerprint и в хранилищах (`shown_findings.db`, `feedback.db`, `suppression`) путь хранится относительно корня проекта, с прямыми слэшами, без ведущего `/` и без префикса `/workspace`. Абсолютный путь допустим только во внутренних логах.

**Действия:**
1. Нормализовать пути в одном месте, сразу после получения результатов от сканеров и до расчёта fingerprint. Точка входа: `normalization/normalizer.py`. Не добавлять отдельные `_relpath` в каждый инструмент.
2. Определить корень проекта для нормализации как `project_path` сессии. При запуске в Docker, если `project_path` равен `/workspace`, относительные пути получаются от него. Путь вне корня проекта не обрезать молча: помечать находку `warnings` и исключать из ответа.
3. Пересчитать fingerprint от нормализованного относительного пути. Иначе `finding_id` будет зависеть от места монтирования.
4. Нормализовать строки сообщений: заменить вхождения абсолютного корня на относительные пути в `message`, `reason`, `warnings`. Это касается и текста ошибок сканеров.
5. Нормализовать `meta.scanned_files` и `files` в `post_tool_use`.
6. Нормализовать пути, которые приходят из входа: `scan_file`, `scan_project`, `auto_fix` (при сопоставлении с `finding_id`), `suppress_finding`, `get_scan_history(file_path)`. Пользователь или агент может передать и абсолютный, и относительный путь, и оба должны давать одинаковый результат.
7. Для обратной совместимости хранилищ: если в `shown_findings.db` или `feedback.db` уже записаны абсолютные пути, добавить миграцию или фильтр по нормализованному пути. Решить это при ревизии, плана миграции пока нет.

**Тесты:** `tests/test_relative_paths.py`:
- сканер возвращает `/workspace/src/a.py` при `project_path=/workspace`, в ответе `src/a.py`;
- тот же файл в локальном проекте `/home/dev/app` даёт тот же `finding_id`;
- путь вне проекта не попадает в ответ и даёт предупреждение;
- в `message` и `reason` нет префикса корня проекта;
- `scan_file` с абсолютным и относительным путём даёт одинаковый результат.

**Критерий готовности:** ни одно поле ответа MCP и ни одно значение в хранилищах не содержит абсолютного пути проекта.

## Этап 2. Блокировка инициализации

**Проблема:** `_ensure_session` и `initialize` не синхронизированы. Параллельные вызовы могут запустить двойную инициализацию и конфликтовать на SQLite.

**Действия:**
1. Добавить `asyncio.Lock` в `SessionState`.
2. Разделить `initialize` на публичный метод с захватом блокировки и внутренний `_initialize_locked`, чтобы не получить взаимную блокировку при вызове изнутри (например, из `update_config`).
3. Проверка `if self.initialized and not force` выполняется внутри блокировки (double-checked).

```python
# mcp-server/src/appsecgate_mcp/server.py
class SessionState:
    def __init__(self) -> None:
        ...
        self._lock = asyncio.Lock()

    async def initialize(self, project_path: str | None = None, *, force: bool = False) -> None:
        async with self._lock:
            if self.initialized and not force:
                return
            await self._initialize_locked(project_path, force=force)
```

**Тесты:** `tests/test_session_lock.py`. Пять параллельных вызовов `_ensure_session` дают одну инициализацию (проверка через счётчик вызовов mock на `init_databases`).

---

## Этап 3. Валидация конфига перед записью

**Проблема:** `update_config` пишет YAML на диск до проверки. Невалидный конфиг сохраняется, и последующий `initialize` падает уже с повреждённым файлом.

**Действия:**
1. Собрать `merged`, проверить его через ту же модель, что использует `ConfigLoader` (уточнить по `loader.py`).
2. Только после успешной проверки записать файл. Запись атомарная: во временный файл, затем `os.replace`.
3. При ошибке валидации вернуть `{"status": "invalid", "errors": [...]}` и не трогать файл.
4. Если переинициализация падает после записи, откатить файл к предыдущей версии.

```python
# mcp-server/src/appsecgate_mcp/server.py
import tempfile

def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
```

**Тесты:** `tests/test_update_config.py`. Невалидный `updates` не меняет файл. Валидный меняет. Ошибка переинициализации откатывает файл.

---

## Этап 4. Вынос hooks из MCP-инструментов

**Проблема:** `session_start`, `pre_tool_use`, `post_tool_use` зарегистрированы как `@mcp.tool()`. Модель может вызвать их сама, а `post_tool_use` запускает сканирование и автофикс.

**Действия:**
1. Перенести логику hooks в `src/appsecgate_mcp/hooks.py` как обычные async-функции.
2. Убрать декораторы `@mcp.tool()` с этих функций.
3. Добавить CLI-подкоманду `appsecgate-mcp hook <name>`, которую вызывают конфиги агентов (Claude Code, Cursor). Она читает JSON из stdin и пишет результат в stdout.
4. Сохранить поведение `post_tool_use` без изменений, кроме границ пути из этапа 1.

**Тесты:** MCP-список инструментов содержит ровно 9 инструментов из README (`scan_file`, `scan_diff`, `scan_project`, `auto_fix`, `get_config`, `update_config`, `submit_feedback`, `get_scan_history`, `suppress_finding`), а hooks доступны через CLI.

---

## Этап 5. Синхронизация документации

**Действия:**
1. Исправить docstring в `server.py`: убрать «9 инструментов и 3 hook-хендлера», описать актуальный состав.
2. В README заменить список инструментов на реальный (9 инструментов из этапа 4). Убрать `report_blocked` или пометить как «не реализован».
3. Исправить сигнатуры в описании hooks.
4. Убрать из Фазы 1 сканеры, которых нет в `scanners/` (Bandit, ESLint, OSV, Checkov, KICS, ZAP), или перенести их в «запланировано».

**Проверка:** тест сравнивает список инструментов из `mcp.list_tools()` с перечнем в README, расхождение валит CI.

---

## Этап 6. Регрессия и приёмка

1. Запустить `make check` (линт и тесты).
2. Прогнать `test_server_smoke.py` и убедиться, что старые сценарии проходят.
3. Вручную проверить сценарии: `scan_file` с путём наружу, `update_config` с невалидным YAML, `scan_diff` в репозитории с изменениями.

---

## Открытые вопросы

1. ~~**Миграция `shown_findings.db` и `feedback.db`.**~~ **Неактуально на текущий момент.** Старые записи с абсолютными путями не мигрируются и не фильтруются: данные в БД не важны, проект на стадии разработки. Нормализация действует на входе и в `items` ответа `get_scan_history`. Вернуться к вопросу, если появятся потребители с сохранёнными данными.
2. **Удаление `_relpath`.** Решить на этапе 1a: удалить, если нормализация в `coordinator._to_finding` его полностью заменяет.
3. **Нормализация сообщений сканеров (этап 1a, пункт 4).** Заменять абсолютный корень в `message` и `reason` строковой заменой или на уровне сканеров. Решить при реализации 1a.

## Критерии готовности

- Ни один инструмент не читает файлы за пределами `project_path`.
- Параллельная инициализация выполняется один раз.
- Невалидный конфиг не попадает на диск.
- Hooks не видны агенту как MCP-инструменты.
- README, docstring и `list_tools()` совпадают.
- Все новые тесты проходят, существующие не сломаны.

---

## Порядок работ

1. Этап 1 (безопасность, блокирует остальное)
2. Этап 3 (целостность данных)
3. Этап 2 (конкурентность)
4. Этап 4 (архитектура hooks)
5. Этап 5 (документация)
6. Этап 6 (регрессия)

---

## Журнал

| Дата | Этап | Статус |
|------|------|--------|
| 2026-10-12 | 1 (защита путей) | Выполнен, `make check` зелёный (129 тестов). Не закрыты: пункты 1a и нормализация путей в ответах. | Добавлен `_resolve_inside_project`; подключён к `scan_file`, `scan_project`, `_extract_touched_files`, `post_tool_use` (ошибка вместо молчаливого сканирования). Добавлен `tests/test_path_guard.py`. Переписан `test_extract_touched_files` на путь внутри временного проекта. Отклонения: проверка `is_file` вместо `exists` в `scan_file`; `_relpath` оставлен в коде без использования; ruff autofix для конца файла теста. |
| 2026-10-12 (`d8fc890`) | 1a, шаг 1 | Выполнен: относительные пути от корня проекта вместо `lstrip('./')`. |
| 2026-10-12 (`d316bbf`) | 1a, шаг 2 | Выполнен: относительные пути до расчёта fingerprint. |
| 2026-10-12 | 1a, шаг 3 (сообщения, warnings, ошибки сканеров, нормализация адаптеров) | Выполнен для gitleaks и trivy, полный прогон 151 passed. Добавлен `BaseScanner.redact_project_root`, применён в `semgrep.py` (warnings, message) и `trivy.py` (message). `gitleaks.py`: `File` через `normalize_path`, `Fingerprint` через `redact_project_root`. `trivy.py`: `Target` и `FilePath` через `normalize_path`. Тесты: `tests/test_scanner_messages.py` (4), `tests/test_gitleaks_adapter.py` (4), `tests/test_trivy_adapter.py` (4), парсинг по JSON-фикстурам без запуска бинарников. Не проверено на реальном выводе: TruffleHog (формат `file_path`), Trivy (нет базы в образе, нужна сеть). Semgrep: тестов парсинга адаптера пока нет. |
| 2026-10-12 | 1a, шаг 4 (`meta.scanned_files`, `files` в `post_tool_use`), удаление `_relpath` | Выполнен, коммит `5135795`. `scan()` нормализует `scanned_files` через `_to_relative`; `project_root is None` не падает. `_relpath` удалён из `server.py`, ссылок в коде и тестах нет. Добавлен `tests/test_scanned_files.py` (4 теста). Полный прогон: 155 passed. Открыто: добавлять ли предупреждение в `meta.warnings` для файлов вне проекта в `scan()`, как в `_relativize()`. |
| — | 2026-10-12 | 1a, шаг 6 (`get_scan_history`: `file_path` на входе, `items` нормализуются, строки вне проекта исключаются) | Выполнен, коммит `8cb415c`. `auto_fix` и `suppress_finding` не требуют нормализации пути: их вход — `finding_id`. Добавлено 7 тестов в `tests/test_history_paths.py`. `ruff --fix` применён к `src/` и `tests/` (5 замечаний). Полный прогон: 162 passed. Открыто: `limit` может быть больше числа записей после фильтрации, так как `LIMIT` применяется в SQL до исключения строк. |
| 2026-10-12 | 3 (валидация `update_config`, атомарная запись, откат) | Выполнен, `make check` зелёный (173 passed). Добавлены `ConfigLoader.merged_layers`, `ConfigLoader.validation_layers` (с `_apply_env_overrides`), `_atomic_write`, шов `_replace_file` для теста сбоя записи, `_format_validation_errors`, `_restore_config`; `tests/test_update_config.py` (6 тестов). Хвосты закрыты: проверка учитывает env-переопределения, тест подменяет `_replace_file`, а не глобальный `os.replace`. Makefile: цель `format` запускает `ruff check --fix` перед `ruff format`. |
| 2026-10-12 | 2 (`asyncio.Lock` в `SessionState`, `_initialize_locked`, double-checked в `initialize`) | Выполнен, `make check` зелёный (173 passed). Добавлен `tests/test_session_lock.py` (4 теста). Вызов `_initialize_locked` под захваченной блокировкой не зависает. |
| — | 4, 5, 6 | Не начаты. Код: нет `hooks.py`; hooks остаются `@mcp.tool()`. |
| — | Тесты этапа 1 | `tests/test_path_guard.py` закоммичен в `73cc481`. `tests/test_server_smoke.py` в рабочей копии не изменён. |