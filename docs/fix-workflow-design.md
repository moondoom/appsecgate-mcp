# Fix Workflow: MCP как поставщик контекста для AI-агента

> **Версия:** 1.0
> **Статус:** Approved for implementation
> **Фаза продукта:** 1 (soft / advisory)
> **Назначение:** описать архитектуру fix-workflow AppSecGate MCP.
> Сервер находит, хранит, трекает и верифицирует находки; фикс генерирует
> и применяет AI-агент своей LLM. В Фазе 1 сервер офлайн, LLM-вызовов на
> сервере нет. В Фазе 2 добавляется центральный сервер агрегации на DuckDB
> и push-only синхронизация.

---

## 1. Проблематика

AppSecGate MCP — сканер-оркестратор. Путь «нашёл → показал» работает.
Путь «исправил» — нет:

- `AutoFixer` читает `finding.metadata["patch"]`, но ни один адаптер этот
  ключ не пишет. Стратегия `patch` мертва.
- `strategy="suggestion"` — заглушка `status="skipped"`.
- `post_tool_use` зовёт `AutoFixer` для top-3 и всегда получает `failed` —
  это шум в контексте агента.
- `mark_fixed` вызывается вслепую — метрики фиктивны.

При этом у AI-агента **уже есть LLM**, Edit/Write и доступ к файлам.
Дублировать LLM на сервере — нарушить офлайн-инвариант, создать
split-source-of-truth и потерять контроль над качеством.

**Задача сервера:** дать агенту максимум контекста, надёжно верифицировать
результат, вести аудит и готовить данные к агрегации в Фазе 2.

---

## 2. Цели и не-цели

### 2.1. Цели Фазы 1

| #  | Цель                                              | Метрика               |
|----|---------------------------------------------------|-----------------------|
| G1 | Агент получает достаточно контекста для фикса     | Verified Findings Rate |
| G2 | Каждая показанная находка доводится до статуса    | Покрытие статусами    |
| G3 | Разработчик видит результат                       | get_scan_history      |
| G4 | Секреты не покидают машину — даже в БД            | Redactor, `redacted=true` |
| G5 | Офлайн, без серверных LLM-вызовов                 | `network_mode: none`  |
| G6 | Данные готовы к агрегации в Фазе 2                | `project_id`, `export_snapshot` |

### 2.2. Не-цели

- Сервер **не генерирует** патчи.
- Сервер **не применяет** патчи (проект `:ro`).
- Сервер **не блокирует** — Фаза 1 soft-контур.
- Сервер **не заменяет CI** — Фаза 2.
- Сервер **не хранит сырые секреты** — даже в БД.
- Сервер **не использует DuckDB** в Фазе 1.
- `AutoFixer`, `FixResult`, `strategy` — **удаляются**.
- Хуки как архитектурная опора — **удаляются** (§4.12).

---

## 3. Пользователи и сценарии

### 3.1. Целевой пользователь

Разработчик с AI-агентом (Claude Code, Cursor, Cline, Continue).
Возможно несколько агентов на одном хосте, работающих с разными проектами.

### 3.2. Сценарии

| #  | Сценарий                                         | Приоритет |
|----|--------------------------------------------------|-----------|
| S1 | Fix workflow: scan → context → fix → verify      | P0        |
| S2 | Явный запрос контекста                           | P0        |
| S3 | Верификация одиночная                            | P0        |
| S4 | Batch fix + verify                               | P0        |
| S5 | Аналитический SQL-запрос                         | P0        |
| S6 | Пакетный триаж (announce → SQL → очередь)        | P1        |
| S7 | Ложное срабатывание                              | P1        |
| S8 | Аудит прогона                                    | P1        |
| S9 | Мультипроект: параллельные агенты                | P0        |

### 3.3. Принцип мягкости

Ни один шаг не обязателен. Метрики измеряют покрытие статусами, не дисциплину.

---

## 4. Архитектура

### 4.1. Схема

```text
┌───────────────────────────────────────────────────────────────┐
│   AI-агент A (proj-a)          AI-агент B (proj-b)            │
│   • своя LLM  • Edit/Write  • MCP-клиент  • DuckDB (опц.)     │
└───────────────────────────────┬───────────────────────────────┘
                                │ stdio MCP / instructions
                                │
┌───────────────────────────────▼───────────────────────────────┐
│   AppSecGate MCP-server (local, offline)                      │
│                                                               │
│   SCAN      ScanCoordinator → 4 адаптера           [есть]     │
│   STORE     shown / identity / context / attempts  [расшир.]  │
│   CONTEXT   ContextBuilder → Redactor → Pack       [новое]    │
│   VERIFY    verify_fix / verify_fix_batch          [новое]    │
│   QUERY     query_findings_db (read-only views)    [новое]    │
│   EXPORT    export_snapshot                        [новое]    │
│   PROTOCOL  MCP server instructions                [новое]    │
│                                                               │
│   Хранилище: одна SQLite, project_id во всех таблицах         │
└───────────────────────────────┬───────────────────────────────┘
                                │
                                │ Фаза 2: push snapshot
                                │ (parquet/ndjson), offline до этого
                                ▼
┌───────────────────────────────────────────────────────────────┐
│   Central AppSecGate Server (Фаза 2, online)                  │
│   DuckDB (OLAP) — агрегация по проектам, тренды, отчёты       │
└───────────────────────────────────────────────────────────────┘
```

### 4.2. MCP-инструменты (9 → 14)

| Инструмент                                | Статус                | Назначение                  |
|-------------------------------------------|-----------------------|-----------------------------|
| `scan_file(path)`                         | есть                  | Скан файла                  |
| `scan_diff()`                             | есть                  | Скан git-изменений          |
| `scan_project(path)`                      | изменён: announce-only | Summary + top-20 + next_actions |
| `get_fix_context(finding_id)`             | новый                 | ContextPack                 |
| `get_fix_context_batch(finding_ids[])`    | новый                 | Batch-контекст (лимит 20)   |
| `verify_fix(finding_id, status, note)`    | новый                 | Верификация                 |
| `verify_fix_batch(attempts[])`            | новый                 | Batch (лимит 20)            |
| `query_findings_db(sql, params)`          | новый                 | Read-only SQL               |
| `export_snapshot(path, format, project_id)` | новый               | Экспорт для Фазы 2 / аналитики |
| `get_scan_history(finding_id?)`           | есть, +расширить      | История                     |
| `submit_feedback(...)`                    | есть                  | Обратная связь              |
| `suppress_finding(...)`                   | есть                  | Подавление                  |
| `get_config()` / `update_config(patch)`   | есть                  | Конфиг                      |
| `auto_fix(...)`                           | удаляется             | —                           |

### 4.3. `scan_project` — announce-only

```json
{
  "project": {"project_id": "a3f2...", "project_alias": "my-app"},
  "summary": {
    "total": 1847,
    "by_severity": {"critical": 3, "high": 45, "medium": 310, "low": 1489},
    "by_category": {"sast": 820, "secret": 27, "sca": 900, "iac": 100},
    "by_file_top10": [{"file_path": "src/auth/login.py", "count": 12}]
  },
  "top_findings": [ "..." ],
  "next_actions": [
    "query_findings_db(\"SELECT logical_id FROM v_findings WHERE severity='high' LIMIT 50\")",
    "get_fix_context(finding_id='...')",
    "get_fix_context_batch(finding_ids=['...', '...'])"
  ],
  "truncated": true,
  "total_available": 1847
}
```

**Не помечает находки `SHOWN`.** Это инвентаризация, не показ.

### 4.4. `query_findings_db(sql, params)` — read-only

**Гарантии:**

- Соединение `mode=ro` (`file:...?mode=ro`).
- Только `SELECT`. Regexp-валидация: `^SELECT`, запрет `;`, `ATTACH`, `PRAGMA`.
- Только публичные views (см. §4.7).
- Timeout 5 с, автоматический `LIMIT 1000`, если не указан явно.
- Автофильтр `project_id = current_project_id`.
- Каждый запрос → `sql_audit_log`.

### 4.5. `ContextPack`

```python
class CodeWindow(BaseModel):
    file_path: str
    language: str = ""
    start_line: int
    end_line: int
    lines: list[str]            # формат: "  42 │ return hashlib.md5(...)"
    finding_lines: tuple[int, int]

class RuleDoc(BaseModel):
    rule_id: str
    scanner: str
    category: str
    cwe: list[str] = []
    owasp: list[str] = []
    references: list[str] = []
    remediation: str | None = None
    known_patch: str | None = None      # semgrep fix / fix_regex
    confidence: str | None = None

class SCAData(BaseModel):
    package: str
    installed_version: str
    fixed_version: str | None = None
    manifest_files: list[str] = []

class ProjectSignals(BaseModel):
    git_diff: str = ""
    feedback_history: list[dict] = []
    is_test_file: bool = False
    related_findings: list[str] = []

class ContextPack(BaseModel):
    project: ProjectRef                  # {project_id, project_alias}
    finding: Finding                     # snippet redacted
    window: CodeWindow | None            # None для sca/license
    rule: RuleDoc
    sca: SCAData | None                  # для sca-находок
    signals: ProjectSignals
    instructions: str
    output_schema: dict
    redacted: bool
    prompt_version: str = "v1"
```

**Формат `lines`:** с номерами в строке (`"  42 │ ..."`) — оптимум для LLM.
**Инструкции:** на английском, adherence выше для Claude Code / Cursor.

### 4.6. `verify_fix` / `verify_fix_batch`

```python
class VerifyResult(BaseModel):
    logical_id: str
    fingerprint: str
    reported_status: str
    verified_status: str          # fixed | not_fixed | regressed | false_positive | wont_fix
    verified: bool
    new_fingerprints: list[str] = []
    reason: str = ""

class BatchVerifyResult(BaseModel):
    results: list[VerifyResult]
    file_rescans: dict[str, str]  # file_path → scan_id
    summary: dict[str, int]
```

**Логика batch:** уникальные `file_path` пересканируются один раз,
затем для каждой находки — сверка `(logical_id, rule_id)`. Лимит 20.

### 4.6.1. Уточнение семантики верификации (решение разработчика)

Набор статусов верификации в реализации: `fixed`, `not_fixed`, `wont_fix`.
Отдельного статуса `regressed` нет: если находка с тем же `logical_id`
появляется вновь после перескана, но `fingerprint` изменился — это
`not_fixed` (т.е. фикс не привёл к устранению находки).

- `wont_fix` — записывается **только** через `verify_fix` / `verify_fix_batch`.
  `suppress_finding` и `submit_feedback(WONT_FIX)` **не** меняют статус
  верификации (suppress — локальный фильтр показа, feedback — офлайн-очередь).
- `note` обязателен для `wont_fix` (несёт пояснение; без него запись
  не считается завершённой).

### 4.7. Хранилище

```sql
-- shown_findings: +project_id, +logical_id, +status_updated_at
ALTER TABLE shown_findings ADD COLUMN project_id TEXT NOT NULL;
ALTER TABLE shown_findings ADD COLUMN logical_id TEXT;
ALTER TABLE shown_findings ADD COLUMN status_updated_at TIMESTAMP;
CREATE INDEX idx_shown_project   ON shown_findings(project_id);
CREATE INDEX idx_shown_logical   ON shown_findings(logical_id);
CREATE INDEX idx_shown_rule_file ON shown_findings(project_id, rule_id, file_path);

-- finding_identity: живёт дольше fingerprint
CREATE TABLE finding_identity (
    logical_id       TEXT NOT NULL,
    project_id       TEXT NOT NULL,
    rule_id          TEXT NOT NULL,
    file_path        TEXT NOT NULL,
    first_seen_at    TIMESTAMP NOT NULL,
    last_fingerprint TEXT NOT NULL,
    last_seen_at     TIMESTAMP NOT NULL,
    PRIMARY KEY (project_id, logical_id)
);

-- finding_context: snippet УЖЕ redacted
CREATE TABLE finding_context (
    fingerprint      TEXT NOT NULL,
    project_id       TEXT NOT NULL,
    logical_id       TEXT NOT NULL,
    rule_id          TEXT NOT NULL,
    file_path        TEXT NOT NULL,
    snippet          TEXT,
    message          TEXT,
    metadata_json    TEXT,
    remediation      TEXT,
    scanner_version  TEXT,
    captured_at      TIMESTAMP NOT NULL,
    PRIMARY KEY (project_id, fingerprint)
);

-- fix_attempts
CREATE TABLE fix_attempts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id         TEXT NOT NULL,
    logical_id         TEXT NOT NULL,
    fingerprint        TEXT NOT NULL,
    rule_id            TEXT NOT NULL,
    file_path          TEXT NOT NULL,
    attempt_num        INTEGER NOT NULL,
    reported_status    TEXT NOT NULL,
    verified_status    TEXT NOT NULL,
    note               TEXT,
    session_id         TEXT NOT NULL,
    agent_reported_at  TIMESTAMP NOT NULL,
    verified_at        TIMESTAMP NOT NULL
);

-- sql_audit_log
CREATE TABLE sql_audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    sql          TEXT NOT NULL,
    duration_ms  INTEGER,
    row_count    INTEGER,
    executed_at  TIMESTAMP NOT NULL
);

-- projects registry
CREATE TABLE projects (
    project_id      TEXT PRIMARY KEY,
    project_alias   TEXT NOT NULL,
    project_path    TEXT NOT NULL,
    first_seen_at   TIMESTAMP NOT NULL,
    last_seen_at    TIMESTAMP NOT NULL
);
```

**Публичные views** (все с `project_id`):

- `v_findings` — текущее состояние находок.
- `v_attempts` — попытки верификации.
- `v_summary` — агрегаты по severity/category/status.
- `v_verification_coverage` — `coverage_pct` по проекту.
- `v_projects` — список проектов.

Версионирование: изменение схемы view — новая (`v_findings_v2`), старая
живёт минимум 2 релиза.

**Retention policy:**

- `SHOWN` без активности 30 дней → **DELETE из `shown_findings`**
  (`finding_identity` остаётся — для детекта рецидивов).
- `FIXED` старше 90 дней → архив.
- `WONT_FIX` / `FALSE_POSITIVE` → 180 дней.
- `fix_attempts` — 180 дней.
- `sql_audit_log` — 30 дней.

### 4.8. `logical_id` — AST-scope + bucket fallback

```python
def compute_logical_id(rule_id, file_path, line_start, source) -> str:
    scope_key = extract_scope_key(source, line_start) or f"L{line_start // 20}"
    return sha256(f"{rule_id}:{file_path}:{scope_key}").hexdigest()[:16]

def extract_scope_key(source: str, line: int) -> str | None:
    """Python: ast.parse → qualified name enclosing symbol.
    Другие языки: None (fallback на bucket)."""
```

**Свойства:**

- Вставка 100 строк выше функции — `scope_key` не меняется.
- Две `hardcoded-secret` в разных функциях — разные `logical_id`.
- Не-Python файлы → bucket по 20 строк.

**Наследование при verify_fix:** новые fingerprint'ы того же `(rule_id,
file_path)` в пределах ±20 строк получают тот же `logical_id`.
Дальше ±20 — новая находка.

### 4.9. Redactor (redaction до записи в БД)

```text
Scanner → RawFinding
  → Normalizer → Finding
  → Redactor.redact_finding()
  → finding_context (маскированный snippet)
  → ContextPack
```

**Следствия:**

- SQL-доступ безопасен: views не содержат сырых секретов.
- Смена политики → `appsecgate-mcp reindex --redaction` (CLI).

**Политика по категориям:**

| Категория | Хранится / отдаётся                          |
|-----------|----------------------------------------------|
| `secret`  | маскированный snippet + rule_id + позиция    |
| `sast`    | полный snippet + rule doc                    |
| `sca`     | package + versions                           |
| `iac`     | полный блок ресурса                          |
| `license` | только метаданные; в ContextPack не идёт     |

**Паттерны:** AWS / GCP / Azure, PEM, JWT, base64-ключи,
high-entropy (Shannon > 4.5, len ≥ 16).

### 4.10. Мультипроектность

**`project_id`:** `sha256(realpath(project_path))[:16]`.
**`project_alias`:** из конфига или basename пути. Хранится в `projects`.

**Правило старта:** `SessionState.initialize()` фиксирует `project_id`.
Смена `project_path` в одной сессии → **ошибка**, не warning.

**Параллельные агенты:** два stdio-процесса MCP → одна SQLite → WAL.
Пишут с разными `project_id`. Коллизий нет.

**Пользователь:** Docker Compose поднимает один контейнер. Volume
`appsecgate-data` — общий. Внутри — SQLite с `project_id`. Ничего
настраивать вручную не нужно.

### 4.11. `export_snapshot` — подготовка к Фазе 2

```python
export_snapshot(
    path: str,
    format: "parquet" | "ndjson",
    project_id: str | None = None
) -> {"path": ..., "row_count": ..., "format": ...}
```

- `format="parquet"` — читается DuckDB без конвертации.
- `project_id=None` — все проекты (для миграции).
- В Фазе 1 — **только локальный файл**, никаких сетевых вызовов.
- В Фазе 2 — добавляется `push_snapshot(url, token)` (push-only).
  **Центральный сервер не имеет доступа к локальным местам.**

**Содержимое снапшота:** `v_findings`, `v_attempts`, `v_summary`,
`v_verification_coverage`, `v_projects`. Плюс `scanner_version`,
`ruleset_hash`, `prompt_version` для трекинга дрейфа в Фазе 2.

### 4.12. Хук (опционально, за рамками Фазы 1)

Не часть архитектуры. Возможен в Фазе 2 как тонкий триггер
(scan_file по Edit/Write) без AutoFixer и `autofixes[]`.

---

## 5. MCP server instructions

На английском. Публикуется через FastMCP `instructions`.

```text
AppSecGate is a security scanner. The server finds, stores, and verifies
findings. The server does NOT generate or apply fixes — the agent does
that with its own LLM.

Fix protocol:
1. After Edit/Write, call scan_file(path).
2. For each finding, call get_fix_context(finding_id). For a group,
   use get_fix_context_batch(finding_ids=[...]).
3. Generate a fix with your LLM. Apply it via Edit/Write.
4. After applying, call verify_fix(...) or verify_fix_batch([...]).
   The server rescans files and confirms the result.
5. If verified=false, the finding is NOT fixed. Retry or mark
   wont_fix with a note.

Bulk queries:
- scan_project returns a summary only (announce). For details use
  query_findings_db with SQL over views.
- Available views: v_findings, v_attempts, v_summary,
  v_verification_coverage, v_projects. SELECT only.

Constraints:
- Do not edit files outside finding.file_path.
- Do not delete secrets from code — suggest rotation via submit_feedback.
- Redacted fields are placeholders; do not attempt to recover them.
- All work is scoped to the current project (project_id).
```

---

## 6. Требования

### 6.1. Функциональные

| #   | Требование                                                    | Приоритет |
|-----|---------------------------------------------------------------|-----------|
| F1  | `get_fix_context` возвращает валидный ContextPack             | P0        |
| F2  | `get_fix_context_batch` — лимит 20                            | P0        |
| F3  | `scan_project` = announce-only, не помечает SHOWN             | P0        |
| F4  | `query_findings_db` — только views, только SELECT             | P0        |
| F5  | Redaction до записи в БД                                      | P0        |
| F6  | `verify_fix` / `verify_fix_batch` — fixed/not_fixed/regressed | P0        |
| F7  | `verify_fix_batch` — лимит 20                                 | P0        |
| F8  | `logical_id` — AST-scope + bucket fallback                    | P0        |
| F9  | `project_id` фиксируется при init, смена → ошибка             | P0        |
| F10 | `project_alias` хранится в `projects`                         | P0        |
| F11 | MCP server instructions (English)                             | P0        |
| F12 | `semgrep.py` кладёт `metadata["patch"]`                       | P0        |
| F13 | Публичные views версионируются                                | P0        |
| F14 | `export_snapshot` — parquet/ndjson                            | P0        |
| F15 | `finding_context` персистентен                                | P0        |
| F16 | `ConfigSuppressFilter`                                        | P1        |
| F17 | Dedup по severity                                             | P1        |
| F18 | Retention policy                                              | P1        |
| F19 | `sql_audit_log`                                               | P1        |

### 6.2. Нефункциональные

| #    | Требование                                   | Значение       |
|------|----------------------------------------------|----------------|
| NF1  | scan_file                                    | < 2 с (p50)    |
| NF2  | get_fix_context (без кэша)                   | < 500 мс       |
| NF3  | get_fix_context_batch (20 шт.)               | < 5 с          |
| NF4  | query_findings_db                            | < 5 с (timeout) |
| NF5  | verify_fix_batch (20 файлов)                 | < 30 с         |
| NF6  | network_mode: none (Фаза 1)                  | Обязательно    |
| NF7  | read_only: true                              | Обязательно    |
| NF8  | Ноль новых production-зависимостей           | Обязательно    |
| NF9  | Redaction секретов                           | 100%           |
| NF10 | Обратная совместимость (8 из 9 тулов)        | Обязательно    |
| NF11 | Промпты не логируются                        | Обязательно    |
| NF12 | SQL timeout                                  | 5 с            |
| NF13 | Параллельные агенты на разных проектах       | Без коллизий   |

---

## 7. Критерии приёмки Фазы 1

### 7.1. Пользовательский

> «Разработчик совместно с агентом верифицирует все находки»

- После `scan_project` находки не помечены `SHOWN`.
- `v_verification_coverage` показывает `coverage_pct` по проекту.
- Каждая находка в работе → запись в `fix_attempts`.
- Находки не «висят» в `SHOWN` > 30 дней (retention).

### 7.2. Технические

- [ ] `AutoFixer`, `FixResult`, `strategy` удалены.
- [ ] `scan_project` возвращает announce-формат.
- [ ] `query_findings_db` отклоняет UPDATE/DELETE/ATTACH/PRAGMA.
- [ ] `finding_context.snippet` без сырых секретов (тест на 10 паттернов).
- [ ] `logical_id` стабилен при вставке 100 строк выше функции.
- [ ] `logical_id` различается для двух находок одного правила в разных функциях.
- [ ] `verify_fix_batch` пересканирует файл 1 раз на N находок.
- [ ] `verify_fix_batch` отклоняет > 20 с понятной ошибкой.
- [ ] Два параллельных MCP-процесса на разных `project_id` — без коллизий.
- [ ] Смена `project_path` в сессии → ошибка.
- [ ] `export_snapshot` в parquet читается DuckDB без потерь.
- [ ] Views документированы и версионированы.
- [ ] `sql_audit_log` пишется.
- [ ] 186 существующих тестов не сломаны.
- [ ] Новые тесты: ContextBuilder, Redactor, logical_id, verify_fix_batch,
      query_findings_db (injection, timeout, LIMIT), project isolation.

### 7.3. Продуктовые

- [ ] Разработчик с Cursor на реальном проекте проходит цикл
      scan → context → fix → verify.
- [ ] Ни один секрет не покинул машину.
- [ ] Контур не блокирует.
- [ ] Два агента на разных проектах работают одновременно.

---

## 8. Роадмап

### 8.1. Этап 0 — гигиена (1 день)

- 0.1. `metadata["patch"] = meta.get("fix")`.
- 0.2. `ConfigSuppressFilter`.
- 0.3. Dedup по severity.
- 0.4. Удалить `AutoFixer`, `FixResult`, `strategy`.
- 0.5. Удалить `autofixes[]` из `post_tool_use`.

### 8.2. Этап 1 — идентичность, проекты, контекст (4–5 дней)

- 1.1. Таблицы `projects`, `finding_identity`, `finding_context`.
- 1.2. `project_id` + `project_alias`; фиксация при init.
- 1.3. `logical_id` — AST-scope + bucket fallback.
- 1.4. `ContextBuilder` + `Redactor` (redaction до записи). ✅
- 1.5. `get_fix_context` + `get_fix_context_batch` (лимит 20). ✅
- 1.6. `scan_project` → announce-only. ✅
- 1.7. Публичные views + `query_findings_db`. ✅
- 1.8. `sql_audit_log`. ✅ (retention — §8.4 п. 3.2)
- 1.9. `export_snapshot` (parquet/ndjson). ✅ (только ndjson; parquet — Фаза 2, нет новых prod-зависимостей)

### 8.3. Этап 2 — верификация (2–3 дня)

- 2.1. Таблица `fix_attempts` с `logical_id`, `session_id`, `project_id`. ✅
- 2.2. `verify_fix` + `verify_fix_batch` (лимит 20). ✅
- 2.3. Индексы и views coverage. ✅ (`v_attempts`, `v_verification_coverage`, `idx_fix_attempts_project`)
- 2.4. Детект регрессии. ✅ (нет отдельного статуса `regressed`: повторный перескан с новым fingerprint при том же `logical_id` → `not_fixed`, F6)
- 2.5. `get_scan_history` расширен. ✅ (поля `attempts`, `verified`, `not_fixed`, `wont_fix`, `coverage`)

### 8.4. Этап 3 — протокол (1–2 дня)

- 3.1. MCP server instructions (English). ✅ (`FastMCP(..., instructions=...)`, текст §5)
- 3.2. Retention policy. ✅ (SHOWN ≥ 30 дней без активности → DELETE из `shown_findings`; `apply_retention()` при init)
- 3.3. Документация для разработчика. ✅ (см. §4.6.1)

### 8.5. Фаза 2 (out of scope)

- Central Server с DuckDB.
- Push-only sync (`push_snapshot(url, token)`).
- CI-гейт, командные политики.
- `pre_tool_use` блокировки.
- GitLab / SARIF-экспорт.
- `tree-sitter` для не-Python scope extraction (если понадобится).

---

## 9. Открытые вопросы

### 9.1. Открытые

| #  | Вопрос                                                            | Влияние         |
|----|-------------------------------------------------------------------|-----------------|
| O1 | Синк Фазы 2: формат снапшота — parquet или ndjson?                | Готовность данных |
| O2 | `project_alias` — из конфига или автогенерация?                   | UX              |
| O3 | Порог активности для retention — 30 дней, конфигурируемый?        | Операции        |
| O4 | `tree-sitter` для не-Python — нужен в Фазе 2 или bucket достаточно? | Качество ID   |
| O5 | `reindex --redaction` — CLI или MCP-тул?                          | UX              |
| O6 | Метрика Agent Fix Rate для SCA (bump версии) — считать как fixed? | Продукт         |

### 9.2. Закрытые в этом документе

- ✅ Архетип A (context-pack) как основной.
- ✅ Удаление AutoFixer, FixResult, strategy.
- ✅ `scan_project` = announce-only.
- ✅ `query_findings_db` — read-only views.
- ✅ Redaction до записи в БД.
- ✅ Batch-верификация с лимитом 20.
- ✅ `logical_id` — AST-scope + bucket fallback.
- ✅ STALE = DELETE (с сохранением `finding_identity`).
- ✅ Формат `CodeWindow.lines` — с номерами в строке.
- ✅ Instructions на английском.
- ✅ SQLite (не DuckDB) в Фазе 1.
- ✅ Мультипроект: `project_id` + `project_alias`.
- ✅ Push-only sync в Фазе 2.
- ✅ SQL-диалект — SQLite (`SELECT`/`GROUP BY`/`WHERE` переносимы).

---

## Список изменений

| Версия | Изменения                                                                                   |
|--------|---------------------------------------------------------------------------------------------|
| 0.1    | Черновик: удаление AutoFixer, MCP + instructions, soft-контур                               |
| 0.2    | `scan_project` announce-only; `query_findings_db`; redaction до записи; batch-верификация; `logical_id`; `session_id`; retention |
| 0.3    | `logical_id` через AST-scope + bucket; STALE → DELETE; лимит batch 20; формат `CodeWindow.lines`; English instructions |
| 1.0    | Мультипроект через `project_id` + `project_alias`; SQLite подтверждён; DuckDB — только Фаза 2 на центральном сервере; `export_snapshot`; push-only sync |