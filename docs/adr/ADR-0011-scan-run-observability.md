# ADR-0011: Scan run observability, passive counters, and pattern promotion

**Статус:** Proposed
**Дата:** 2026-11-01
**Файл:** `docs/adr/ADR-0011-scan-run-observability.md`
**Контекст:** ADR-0004 (master, event sourcing), ADR-0007 (per-branch), ADR-0009 (agent model) вместе дают события, аудит и agent-цикл, но не дают «scan run» как first-class сущности. Master знает про находки (`finding_shown`), но не знает «сколько было сканов», «какой вердикт у репозитория», «что изменилось между сканами». Нет пассивной телеметрии проекта (языки, lock-файлы, security-конфиги), нет LLM-описания проекта, нет оценки соответствия security-паттернам, нет пути «advisory от LLM → детерминированное правило». Плюс на находках нет `last_seen_scan_id` — нельзя ответить «когда последний раз видели эту находку».
**Связанные:** ADR-0001 (fingerprint), ADR-0004 (master), ADR-0006 (lifecycle / gate matrix), ADR-0007 (per-branch), ADR-0008 (orchestrator modes), ADR-0009 (agent model)

---

## 1. Контекст

### 1.1. Что уже есть

- **Master (ADR-0004):** event sourcing, `audit_log` append-only, `POST /v1/events`, `GET /v1/findings`, `GET /v1/suppressions`, `GET /v1/config`, `GET /v1/audit`, `GET /healthz`. Идемпотентность по `client_event_id`.
- **Per-branch (ADR-0007):** события несут `branch`/`commit`; агрегация `(project, branch, fp)`.
- **Agent model (ADR-0009):** контракт `scan_* → check_gate → recommended_action → report`; `check_gate` — advisory `GateSummary`; `action_log.ndjson` — аудит вызовов тулов.
- **Edge (architecture §3.5):** `shown_findings`, `feedback`, `scan_cache` в SQLite на volume.

### 1.2. Чего нет

1. **`scan_run` как first-class.** История есть как поток событий и `action_log`, но «скан #N как единица» — нет. Нельзя ответить «последний скан», «сколько сканов за неделю», «какой вердикт у репозитория», «что изменилось между сканами #M и #N».
2. **«Safe mark» / repo status.** `check_gate` — advisory в моменте; master не персистит «этот репозиторий чистый».
3. **Пассивная телеметрия проекта.** Языки, lock-файлы, security-конфиги, тестовые директории — детерминированные сигналы adoption процессов безопасности. Сейчас не собираются.
4. **LLM-описание проекта.** Нет «краткого описания» стека, фреймворков, архитектуры.
5. **Оценка соответствия security-паттернам.** Нет библиотеки паттернов («есть ли rate limiting на auth-эндпоинтах», «есть ли CSRF-защита на state-changing form»), нет стадии assessment.
6. **Путь «advisory → детерминизм».** Частые LLM-обнаружения не превращаются в детерминированные правила — каждый скан платит токенами за одно и то же.
7. **`last_seen_scan_id` на находках.** `shown_findings` знает `last_shown_at`, но не «в каком скане последний раз видели».
8. **Фиксация модели.** `scan_completed` не фиксирует, какая LLM делала триаж/описание — сравнение моделей между сканами невозможно постфактум.

### 1.3. Ограничения (инварианты)

- **№1** проект монтируется `:ro` — сервер не пишет файлы проекта.
- **№2** MCP-сервер `network_mode: none`; сеть — только у edge-процесса на хосте (ADR-0004 §4.2).
- **№4** redaction: только агрегаты/ссылки, никакого кода и секретов.
- **№5** `query_findings_db` — только SELECT по публичным views.
- **Fail-closed** (MS-6): CI без master — exit 2.

---

## 2. Цели и не-цели

### 2.1. Цели

| # | Цель | Метрика |
|---|------|---------|
| G1 | `scan_run` — first-class сущность на edge и master, с историей | `GET /v1/scans` возвращает историю; `GET /v1/scans/{id}` — детали |
| G2 | Детерминированный `verdict ∈ {clean, issues, blocked, unknown}` о репозитории по результатам скана | `GET /v1/repo-status` возвращает `verdict` + `prev_verdict` + `changed_at` |
| G3 | Пассивные счётчики проекта в каждом скане | `scan_completed.counters` заполнен для 100% сканов |
| G4 | LLM-описание проекта как advisory | `project_summary` есть в `GET /v1/scans/{id}` |
| G5 | LLM-оценка соответствия security-паттернам как advisory | `assessment_summary` есть для всех `active` паттернов |
| G6 | Loop «advisory → детерминизм» через promotion | `pattern_promotion_candidates` + `pattern_library.deterministic_rule_id` |
| G7 | `last_seen_scan_id` на находках (edge + master) | Заполнен для 100% находок после скана |
| G8 | Фиксация `llm_model` / `llm_backend` в `scan_completed` | Разные модели → разные `llm_model` в истории |
| G9 | Инварианты №1, №2, №4 не нарушены; fail-closed сохранён | Регрессионные тесты зелёные |

### 2.2. Не-цели

- Web UI / BI (Фаза 4).
- RBAC (Фаза 3).
- Автоматическое написание детерминированных правил без human review.
- Сканирование контейнерных образов, IaC (вне scope).
- Изменение `GateEngine` / матрицы ADR-0006.
- Изменение контракта `check_gate` (ADR-0009 §3).

---

## 3. Инвариант: deterministic vs advisory

Фундамент ADR. Без него «safe mark» становится управляемым LLM — это дыра.

| Источник | Влияет на `verdict`? | Тип события | Где хранится |
|----------|----------------------|-------------|--------------|
| Findings сканеров (Semgrep/Gitleaks/Trivy/TruffleHog) | ✅ да | `finding_shown` | edge `shown_findings` → master `finding_aggregates` |
| `GateEngine` (матрица ADR-0006 §2.3) | ✅ да | — (вычисление) | `scan_completed.verdict` |
| Пассивные счётчики (§5) | ❌ нет (в событии — да) | `scan_completed.counters` | edge `scan_runs` → master `scan_runs` |
| LLM-триаж FP/TP | ❌ **advisory** | `triage_summary` | `triage_summaries` |
| LLM project summary | ❌ **advisory** | `project_summary` | `project_summaries` |
| LLM pattern assessment | ❌ **advisory** | `assessment_summary` | `assessment_summaries` |

**Правила:**
1. `verdict` вычисляется **до** чтения LLM-выхода.
2. `emit_scan_completed` **не принимает** `verdict` от агента — считает внутри из `shown_findings` + `GateEngine`. Если агент передаёт `verdict` — игнорируется с warning.
3. Каждый advisory-объект несёт `"advisory": true` и `"source": "llm:<model>"`; API возвращает это явно.
4. Unit-тест: «подать заведомо ложный FP-вердикт (100% находок → FP) → `verdict` не изменился». Обязателен.

**Обоснование:** `verdict=clean` — утверждение о безопасности. Если LLM может его сформировать, prompt injection / галлюцинация / «утоворить модель» превращают safe mark в фикцию. Advisory-данные остаются видимыми и полезными (сравнение моделей, тренды, кандидаты на промоушен), но не определяют вердикт.

---

## 4. Решение: `scan_run` как first-class

### 4.1. Edge SQLite: `scan_runs`

```sql
CREATE TABLE scan_runs (
  scan_run_id        TEXT PRIMARY KEY,           -- uuid, генерируется агентом
  project_id         TEXT NOT NULL,
  branch             TEXT NOT NULL,              -- ADR-0007
  commit_sha         TEXT NOT NULL,
  scope              TEXT NOT NULL,              -- full|diff|file
  started_at         TIMESTAMP NOT NULL,
  completed_at       TIMESTAMP,
  status             TEXT NOT NULL,              -- running|completed|partial|failed
  llm_model          TEXT,                       -- qwen2.5-coder-32b
  llm_backend        TEXT,                       -- vllm|ollama|litellm:<key-name>
  agent_version      TEXT NOT NULL,
  mcp_version        TEXT NOT NULL,
  scanner_versions_json TEXT NOT NULL,           -- {"semgrep":"...","gitleaks":"...","trivy":"..."}
  ruleset_hash       TEXT NOT NULL,              -- ADR-0001 / architecture §8.1
  counters_json      TEXT NOT NULL,              -- §5
  verdict            TEXT,                       -- clean|issues|blocked|unknown (deterministic)
  verdict_reason_json TEXT,                      -- breakdown по ADR-0006 §2.3
  warnings_json      TEXT,
  synced_at          TIMESTAMP
);
CREATE INDEX idx_scan_runs_pb ON scan_runs(project_id, branch, completed_at);
```

`scan_run_id` генерируется агентом при `emit_scan_started`; тот же `scan_run_id` используется во всех событиях прогона — связность.

### 4.2. Edge SQLite: `shown_findings` — расширение

```sql
ALTER TABLE shown_findings ADD COLUMN first_seen_scan_id TEXT;
ALTER TABLE shown_findings ADD COLUMN last_seen_scan_id  TEXT;
ALTER TABLE shown_findings ADD COLUMN first_seen_at      TIMESTAMP;
ALTER TABLE shown_findings ADD COLUMN last_seen_at       TIMESTAMP;
```

Обновляется при каждом прогоне, который «увидел» находку. Backward compat: для старых записей — NULL, заполняется при следующем скане.

### 4.3. Master: materialized views (из `audit_log`, ADR-0004 §5.3)

```sql
CREATE TABLE scan_runs (
  scan_run_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  branch TEXT NOT NULL,
  commit_sha TEXT NOT NULL,
  scope TEXT NOT NULL,
  started_at TIMESTAMP NOT NULL,
  completed_at TIMESTAMP NOT NULL,
  status TEXT NOT NULL,
  llm_model TEXT, llm_backend TEXT,
  agent_version TEXT NOT NULL, mcp_version TEXT NOT NULL,
  scanner_versions_json TEXT NOT NULL, ruleset_hash TEXT NOT NULL,
  counters_json TEXT NOT NULL,
  verdict TEXT, verdict_reason_json TEXT,
  warnings_json TEXT,
  client_event_id TEXT NOT NULL UNIQUE
);
CREATE INDEX idx_scan_runs_pb ON scan_runs(project_id, branch, completed_at);
```

`scan_runs` — **производная**; источник истины — `audit_log`. Пересобирается полным fold'ом событий (идемпотентно).

### 4.4. Master: advisory-таблицы

```sql
CREATE TABLE triage_summaries (
  scan_run_id TEXT PRIMARY KEY REFERENCES scan_runs(scan_run_id),
  model TEXT, fp_count INTEGER, tp_count INTEGER,
  suspicious_no_context INTEGER, verdict_llm TEXT,  -- advisory
  completed_at TIMESTAMP
);

CREATE TABLE project_summaries (
  scan_run_id TEXT PRIMARY KEY REFERENCES scan_runs(scan_run_id),
  model TEXT, summary TEXT,
  languages_detected_json TEXT, frameworks_json TEXT,
  confidence REAL, completed_at TIMESTAMP
);

CREATE TABLE assessment_summaries (
  scan_run_id TEXT NOT NULL REFERENCES scan_runs(scan_run_id),
  pattern_id TEXT NOT NULL,
  status TEXT NOT NULL,               -- pass|fail|partial|not_applicable|unsure
  source TEXT NOT NULL,               -- llm|deterministic
  evidence_refs_json TEXT,            -- [{file, line}]
  confidence REAL,
  PRIMARY KEY (scan_run_id, pattern_id)
);
```

### 4.5. Master: `finding_aggregates` — расширение

```sql
ALTER TABLE finding_aggregates ADD COLUMN last_seen_scan_id TEXT;
ALTER TABLE finding_aggregates ADD COLUMN last_seen_at TIMESTAMP;
```

Обновляется из `finding_shown` (в событие добавляется `scan_run_id`).

---

## 5. Пассивные счётчики проекта

Детерминированно, из файловой системы (`:ro`). Источник для «adoption процессов безопасности» без LLM.

```json
{
  "files_by_language": {"python": 128, "javascript": 47, "go": 0, "unknown": 3},
  "loc_estimate": 18420,
  "lock_files": {
    "package-lock.json": true, "poetry.lock": false,
    "go.sum": false, "Cargo.lock": false, "pom.xml": false
  },
  "ci_configs": {
    ".github/workflows": 2, ".gitlab-ci.yml": false,
    ".circleci": false, "Jenkinsfile": false
  },
  "security_configs": {
    ".appsecgate-mcp/config.yaml": true,
    ".pre-commit-config.yaml": true,
    "dependabot.yml": false,
    "gitleaks.toml": false,
    "semgrep.yml": false
  },
  "sbom_present": false,
  "test_dirs_present": ["tests/", "__tests__/"],
  "dockerfile_present": true,
  "iac_files": {"terraform": 0, "k8s": 0, "helm": 1}
}
```

**Свойства:**
- Детерминированный обход (read-only); эвристика по расширениям для языков; опционально tree-sitter.
- В `scan_completed.counters` — но **не** в `verdict` (инвариант §3).
- Тренд по сканам — adoption: «появился `pre-commit-config.yaml` в скане #N».
- **Ограничения:** LOC и языки — эвристика; `lock_files` — по имени; `ci_configs` — по путям. Документируется в §11.

---

## 6. LLM-выходы: advisory

### 6.1. `triage_summary`

```json
{
  "client_event_id": "uuid",
  "event_type": "triage_summary",
  "scan_run_id": "uuid",
  "model": "qwen2.5-coder-32b",
  "findings_triaged": 42,
  "fp_count": 8,
  "tp_count": 34,
  "suspicious_no_context": 2,
  "verdict_llm": "clean|issues|blocked",  // advisory, НЕ влияет на repo_status
  "advisory": true,
  "completed_at": "..."
}
```

Master хранит, **не** использует `verdict_llm` в `repo_status`. Служит для: сравнения моделей (тест-план, A8), тренда FP-rate, метрики `kimi`-триажа в тесте.

### 6.2. `project_summary`

```json
{
  "client_event_id": "uuid",
  "event_type": "project_summary",
  "scan_run_id": "uuid",
  "model": "qwen2.5-coder-32b",
  "summary": "Web API на FastAPI + React, ...",
  "languages_detected": ["python", "javascript"],
  "frameworks": ["FastAPI", "React"],
  "confidence": 0.82,
  "advisory": true
}
```

### 6.3. `assessment_summary` (по одному на pattern)

```json
{
  "client_event_id": "uuid",
  "event_type": "assessment_summary",
  "scan_run_id": "uuid",
  "pattern_id": "auth-rate-limiting",
  "status": "fail",
  "source": "llm",                    // llm|deterministic
  "evidence_refs": [{"file": "src/auth.py", "line": 42}],
  "confidence": 0.76,
  "advisory": true
}
```

Дедуп на приёме: `(scan_run_id, pattern_id)`.

---

## 7. Pattern library и promotion loop

### 7.1. Таблицы

```sql
CREATE TABLE pattern_library (
  pattern_id TEXT PRIMARY KEY,
  description TEXT NOT NULL,
  cwe_refs TEXT,
  detection_hint TEXT,                    -- для LLM
  deterministic_rule_id TEXT,             -- NULL = ещё не промоутнут
  status TEXT NOT NULL,                   -- active|deprecated|promoted
  created_at TIMESTAMP NOT NULL,
  promoted_at TIMESTAMP
);

CREATE TABLE pattern_promotion_candidates (
  candidate_id TEXT PRIMARY KEY,
  pattern_id TEXT NOT NULL REFERENCES pattern_library(pattern_id),
  occurrence_count INTEGER NOT NULL,
  distinct_projects INTEGER NOT NULL,
  evidence_sample_json TEXT,
  status TEXT NOT NULL,                   -- pending|approved|rejected
  created_at TIMESTAMP NOT NULL,
  reviewed_at TIMESTAMP,
  reviewed_by TEXT
);
```

Источник истины — master; edge получает кэш через sync (`GET /v1/pattern-library`) в `~/.cache/appsecgate/patterns.json`.

### 7.2. Жизненный цикл

```
[curated]   pattern_library: pattern_id, description, detection_hint,
            deterministic_rule_id = NULL, status = active
    │
    │  LLM assessment на каждом скане → assessment_summary (advisory)
    ▼
[observed]  master агрегирует: pattern X = fail/partial в N проектах
    │
    │  триггер промоушена (условия ниже)
    ▼
[candidate] pattern_promotion_candidates.status = pending
    │
    │  human review: пишет deterministic rule (Semgrep/custom),
    │  обновляет pattern_library.deterministic_rule_id, status = promoted
    ▼
[promoted]  следующие сканы: source = deterministic для этого pattern;
            LLM assessment для него отключён (экономия токенов)
```

### 7.3. Триггер промоушена

Master вычисляет кандидатов после каждого `assessment_summary`. Условия (все):

- `status ∈ {fail, partial}` в **≥ N различных проектах** (N = 5 по умолчанию, конфигурируется);
- `deterministic_rule_id IS NULL`;
- `evidence_refs` консистентны (один и тот же CWE / тип кода в ≥ 80% случаев);
- нет открытого `pending`-кандидата на этот pattern.

При выполнении — запись в `pattern_promotion_candidates`, `status=pending`. Master **не** создаёт правило сам — human-in-the-loop (ревью, написание правила, обновление library).

### 7.4. После промоушена

- `pattern_library.deterministic_rule_id` заполнен, `status=promoted`, `promoted_at`.
- Следующий sync обновляет кэш на edge.
- Агент при assessment: для промоутнутых паттернов **не вызывает LLM**; `source=deterministic`, `evidence_refs` из детерминированной проверки.
- Экономия: каждый промоутнутый паттерн убирает один LLM-вызов из assessment на каждый скан.

### 7.5. Связь с ADR-0009 §3 (`check_gate`)

`check_gate` **не меняется**. Promotion — про assessment, не про gate. `GateSummary` остаётся advisory; `verdict` в `scan_completed` — детерминированный, строится из `GateEngine`, к промоушену отношения не имеет.

---

## 8. MCP-тулы (расширение architecture §3.1, ADR-0009 §2.1)

Новые тулы — **только локальная запись**; сеть не появляется (инвариант №2).

```python
@mcp.tool()
def emit_scan_started(scope: str, commit_sha: str) -> str:
    """Возвращает scan_run_id. Пишет в edge SQLite + outbox."""

@mcp.tool()
def emit_scan_completed(
    scan_run_id: str,
    counters: dict,           # из get_project_counters() или собран агентом
    warnings: list[str] = [],
) -> None:
    """verdict вычисляется внутри тула из GateEngine.
       НЕ принимает verdict от агента. Ключевая защита от подделки."""

@mcp.tool()
def get_project_counters() -> dict:
    """Детерминированный обход проекта (read-only). §5."""

@mcp.tool()
def get_pattern_library() -> list[dict]:
    """Читает локальный кэш library (последний sync с master)."""

@mcp.tool()
def submit_triage_summary(scan_run_id: str, summary: dict) -> None:
    """Advisory. Валидируется схемой; в verdict не попадает."""

@mcp.tool()
def submit_project_summary(scan_run_id: str, summary: dict) -> None:
    """Advisory."""

@mcp.tool()
def submit_assessment(scan_run_id: str, assessments: list[dict]) -> None:
    """Advisory. assessments: [{pattern_id, status, evidence_refs, confidence}]."""
```

**Ключевое:** `emit_scan_completed` **не принимает `verdict`**. Вердикт считается внутри из `shown_findings` + `GateEngine`. Если агент передаёт `verdict` в kwargs — игнорируется, warning в лог.

**Контракт агента (ADR-0009 §2.1) расширяется:**

```
1. get_config()
2. get_pattern_library()             → список активных паттернов
3. emit_scan_started(scope, commit)  → scan_run_id
4. scan_project() | scan_diff()      → findings
5. query_findings_db(...)            → контекст
6. get_fix_context_batch(fps)        → код
7. [fix code]
8. verify_fix_batch(fps)
9. suppress_finding(...)
10. submit_triage_summary(scan_run_id, ...)      [advisory]
11. submit_project_summary(scan_run_id, ...)     [advisory]
12. submit_assessment(scan_run_id, ...)          [advisory]
13. emit_scan_completed(scan_run_id, counters)   → verdict (deterministic)
14. check_gate(scope, policy)                    → GateSummary (advisory)
15. [report]
```

`check_gate` остаётся «итоговым решением» по политике; `emit_scan_completed` — «штамп о состоянии репозитория». Они не конфликтуют: `check_gate` — про действие агента сейчас, `scan_completed` — про историю репозитория.

---

## 9. События (расширение ADR-0004 §5.1)

Существующие события **не ломаются**; добавляются опциональные поля. Новые типы — с тем же `client_event_id` и идемпотентностью.

| Тип | Источник | Обязательные поля | Назначение |
|-----|----------|-------------------|------------|
| `scan_started` | edge | `scan_run_id`, `project_key`, `branch`, `commit`, `scope`, `started_at`, `llm_model`, `agent_version` | Master-side hung detection |
| `scan_completed` | edge | + `completed_at`, `status`, `scanner_versions`, `ruleset_hash`, `counters`, `verdict`, `verdict_reason`, `warnings` | **Deterministic** основа |
| `triage_summary` | edge | `scan_run_id`, `model`, `fp_count`, `tp_count`, `suspicious_no_context`, `verdict_llm`, `advisory: true` | LLM-триаж |
| `project_summary` | edge | `scan_run_id`, `model`, `summary`, `languages_detected`, `frameworks`, `confidence`, `advisory: true` | LLM-описание |
| `assessment_summary` | edge | `scan_run_id`, `pattern_id`, `status`, `source`, `evidence_refs`, `confidence`, `advisory: true` | LLM-assessment (по одному на pattern) |
| `finding_shown` | edge | + `scan_run_id` (опционально, для backward compat) | Связка finding ↔ scan |

**Redaction (инвариант №4):** `scan_completed`, `triage_summary`, `project_summary`, `assessment_summary` — только агрегаты/ссылки (`file:line`), никакого кода и секретов. `evidence_refs` — только пути и номера строк.

**Идемпотентность:** повторный push с тем же `client_event_id` отбрасывается. `assessment_summary` — несколько событий на `scan_run_id` (по одному на pattern), у каждого свой `client_event_id`; дедуп на приёме по `(scan_run_id, pattern_id)`.

**Fail-closed:** если master недоступен, `scan_completed` копится в `outbox.ndjson` (MS-3); `verdict` в edge `scan_runs` всё равно вычислен (детерминированный); после восстановления — доезжает.

---

## 10. API master (расширение ADR-0004 §5.2)

| Метод | Путь | Назначение |
|-------|------|------------|
| `GET` | `/v1/repo-status?project=&branch=` | Последний `scan_completed`: `verdict`, `scan_run_id`, `completed_at`, `commit`, `prev_verdict`, `changed_at` |
| `GET` | `/v1/scans?project=&branch=&since=&limit=` | История `scan_completed` (пагинация) |
| `GET` | `/v1/scans/{scan_run_id}` | Детали прогона + связанные `triage_summary`, `project_summary`, `assessment_summary` |
| `GET` | `/v1/scans/{scan_run_id}/counters` | Только пассивные счётчики |
| `GET` | `/v1/projects/{project}/trends?metric=&since=` | Тренд счётчиков и compliance по паттернам |
| `GET` | `/v1/pattern-library` | Текущая библиотека (для edge sync) |
| `GET` | `/v1/pattern-promotion/candidates?status=pending` | Кандидаты на промоушен |
| `PATCH` | `/v1/pattern-library/{pattern_id}` | Обновить `deterministic_rule_id` / `status` (admin) |
| `POST` | `/v1/pattern-promotion/{candidate_id}/review` | `approve` / `reject` (admin) |

`GET /v1/findings` **не меняется** — но `finding_aggregates` теперь содержит `last_seen_scan_id`. `GET /v1/audit` без изменений.

**Admin-эндпоинты** (`PATCH pattern-library`, `POST review`) — требуют отдельного scope (`admin`), не project Bearer. Механизм — в ADR-0004 §5.2 (Bearer project-scoped); admin-scope добавляется как отдельный тип ключа. Детали — open question (§14).

---

## 11. Безопасность и инварианты

| Инвариант | Как соблюдается |
|-----------|-----------------|
| **№1** проект `:ro` | `get_project_counters()` только читает; `emit_scan_*` пишут в edge SQLite/outbox, не в проект |
| **№2** MCP без сети | Новые тулы — локальная запись; сеть — только edge sync (`appsecgate-mcp sync`, ADR-0004 §4.2) |
| **№4** redaction | `scan_completed` / `triage_summary` / `project_summary` / `assessment_summary` — агрегаты и `file:line`, не код и не секреты |
| **Fail-closed** | Master недоступен → `outbox` растёт, `verdict` в edge валиден, sync — при восстановлении; CI по-прежнему exit 2 (MS-6) |
| **`emit_scan_completed` не принимает verdict** | Защита от подделки вердикта агентом; warning в лог при попытке |
| **Advisory-флаги** | Каждый advisory-объект несёт `advisory: true`, `source: llm:<model>`; API возвращает явно |
| **PII / секреты в LLM** | `project_summary` / `assessment_summary` проходят redaction на приёме (master) — по аналогии с ADR-0004 §5.4; в `evidence_refs` только пути/строки |
| **Prompt injection** | LLM-выход в `evidence_refs` валидируется схемой (`{file: str, line: int}`); свободный текст только в `summary` (advisory, не парсится как код) |
| **Pattern library** | Master — источник истины; edge — кэш; `ruleset_hash` учитывает версию library (architecture §8.1) — инвалидация кэша при изменении |

---

## 12. Влияние на другие ADR

| ADR | Что меняется |
|-----|--------------|
| **ADR-0001** | Без изменений. `fingerprint` не трогаем. `ruleset_hash` теперь включает версию `pattern_library`. |
| **ADR-0004** | §5.1 — новые типы событий; §5.2 — новые эндпоинты; §5.4 — `scan_runs` как materialized view; конфликт-резолюция §5.3 без изменений (события immutable, идемпотентность та же). |
| **ADR-0006** | Без изменений. `verdict_reason` ссылается на reason'ы §2.3. |
| **ADR-0007** | `scan_completed` обязательно с `branch`/`commit`; `finding_aggregates` — `(project, branch, fp)` + `last_seen_scan_id`. |
| **ADR-0008** | Режимы оркестрации не меняются; `check_gate` (OR-1) остаётся. |
| **ADR-0009** | §2.1 контракт агента расширяется новыми шагами (§8); `GateSummary` не меняется; `action_log` дополняется `scan_run_id`. |
| **architecture.md** | §3.1 Tool Router — новые тулы; §3.5 Storage — `scan_runs`, `pattern_library` (кэш); §4.1 поток — добавить шаг `emit_scan_*`. |

---

## 13. План внедрения

| # | Задача | Зависит | Репо |
|---|--------|---------|------|
| **RSS-1** | Принятие ADR-0011; обновление `docs/adr/README.md`, `docs/architecture.md` §3.1/§3.5, `docs/open-tasks.md` | — | docs |
| **RSS-2** | Edge schema: `scan_runs`, `shown_findings` + `*_scan_id`, `outbox` — новые типы | RSS-1 | mcp-server |
| **RSS-3** | MCP-тулы: `emit_scan_started`, `emit_scan_completed` (verdict внутри), `get_project_counters`, `get_pattern_library`, `submit_triage_summary`, `submit_project_summary`, `submit_assessment` | RSS-2 | mcp-server |
| **RSS-4** | Master schema + materialized views: `scan_runs`, `triage_summaries`, `project_summaries`, `assessment_summaries`, `pattern_library`, `pattern_promotion_candidates`; `finding_aggregates.last_seen_scan_id` | RSS-1 | appsecgate-master |
| **RSS-5** | Master API: `/v1/repo-status`, `/v1/scans`, `/v1/scans/{id}`, `/v1/scans/{id}/counters`, `/v1/projects/{p}/trends`, `/v1/pattern-library`, `/v1/pattern-promotion/*` | RSS-4 | appsecgate-master |
| **RSS-6** | Edge sync: поддержка новых типов событий; pull `pattern_library` в кэш | RSS-3, RSS-5 | mcp-server |
| **RSS-7** | Promotion loop: детектор кандидатов (N≥5), human review flow, `PATCH pattern-library` | RSS-5 | appsecgate-master |
| **RSS-8** | Интеграция в агент: контракт §8; обновление AGENTS.md; пример workflow | RSS-3, RSS-6 | mcp-server / docs |
| **RSS-9** | Тесты (см. §14); документация (README, deploy) | RSS-2…RSS-8 | все |

**MVP (RSS-2…RSS-6, RSS-9)** — закрывает observability, счётчики, LLM-описание, `last_seen_scan_id`, фиксацию модели. **Promotion (RSS-7)** — отдельный этап после MVP (нужен human review, накопление данных).

---

## 14. Тестирование

### 14.1. Unit

- **Детерминизм вердикта:** `emit_scan_completed` с 100% FP от LLM → `verdict` не изменился.
- **Вердикт из `GateEngine`:** matrix ADR-0006 §2.3 — все reason'ы покрыты.
- **Идемпотентность:** повторный `client_event_id` — отбрасывается.
- **Redaction:** попытка передать код/секрет в `evidence_refs` — отклонена.
- **Promotion detector:** N=5 проектов с `pattern X = fail` → 1 кандидат; 4 — нет; повторный — не дублирует.

### 14.2. Контрактные

- OpenAPI master против edge-клиента (schema-driven).
- `assessment_summary` — дедуп по `(scan_run_id, pattern_id)` на приёме.

### 14.3. Интеграция

- Edge → master: `scan_started` → `scan_completed` → `repo-status` возвращает verdict.
- `last_seen_scan_id` propagation: edge `shown_findings` ↔ master `finding_aggregates`.
- Pattern library sync: master `PATCH` → edge кэш обновлён → следующий скан использует.
- Fail-closed: master недоступен → `outbox` растёт, `verdict` валиден, после sync — доезжает.

### 14.4. E2E (опционально — подфаза 1C тест-плана)

| ID | Проверяет |
|----|-----------|
| T-13 | `scan_completed` emitted после `appsecgate ci` |
| T-14 | `repo-status` и `scans` API работают |
| T-15 | `last_seen_scan_id` обновляется |
| T-16 | LLM всё пометил FP → `verdict` не изменился |
| T-17 | `project_summary` есть, `advisory: true` |
| T-18 | `assessment_summary` есть для всех `active` patterns |
| T-19 | Разные модели → разные `llm_model` в `scan_completed` |
| T-20 | Master недоступен → `outbox` → sync → доехало |
| T-21 | Promotion candidate после N=5 проектов |
| T-22 | Post-promotion: `source=deterministic`, LLM для pattern не вызывается |

**В плане тестирования (финальная редакция):** подфаза 1C **опциональна** — активируется, если фича реализована к Стадии 1. Иначе — отдельный приёмочный тест по RSS-9.

### 14.5. Регрессия

- `make check` (mcp-server) зелёный.
- `make check` (appsecgate-master) зелёный.
- Тесты ADR-0004 §9 (aggregate, idempotency, redaction) — зелёные.

---

## 15. Открытые вопросы

| # | Вопрос | Предложение |
|---|--------|-------------|
| 1 | **N для промоушена** | 5 различных проектов по умолчанию; конфигурируется per-pattern или глобально (env `APPSECGATE_PROMOTION_THRESHOLD`) |
| 2 | **`pattern_library` — где живёт** | Master — источник истины, edge — кэш через sync. Альтернатива (статический файл в образе) отклонена: промоушен не пропагируется |
| 3 | **Судьба `triage_summary.verdict_llm`** | Хранить: это данные для сравнения моделей (тест-план). В `repo_status` не входит |
| 4 | **Admin-scope для `PATCH pattern-library`** | Отдельный тип ключа (не project Bearer). Детали — ADR-0004 extension или отдельный mini-ADR |
| 5 | **Retention advisory-таблиц** | `triage_summaries`, `project_summaries`, `assessment_summaries` — без retention (компактны); при росте — TTL 180 дней (отдельный этап) |
| 6 | **`project_summary` — одна на `scan_run_id` или несколько** | Одна; повторный `submit_project_summary` с тем же `scan_run_id` — LWW по `completed_at` |
| 7 | **`assessment_summary` — что если LLM не оценил pattern** | `status=not_applicable` или событие отсутствует; `GET /v1/scans/{id}` возвращает missing patterns отдельно |
| 8 | **UI/API: как показывать `advisory` vs `deterministic`** | Явный `source` + `advisory` флаги в ответе; UI — отдельная иконка (Фаза 4) |
| 9 | **`loc_estimate` — точность** | Эвристика (число строк); tree-sitter — опция; документировать как «estimate» |
| 10 | **Модель по умолчанию для `project_summary` / `assessment`** | Дешёвая (Qwen 7B / GLM 9B); конфигурируется; фиксируется в `scan_completed.llm_model` |

---

## 16. Итог

- **`scan_run` — first-class** на edge и master; `scan_started` / `scan_completed`; `GET /v1/scans`, `GET /v1/repo-status`.
- **Детерминированный `verdict`** (`clean|issues|blocked|unknown`) из `GateEngine`; `emit_scan_completed` не принимает verdict от агента.
- **Пассивные счётчики** — deterministic, в `scan_completed.counters`, не в verdict; тренд adoption без LLM.
- **LLM-описание и assessment** — advisory; `project_summary`, `assessment_summary`, `triage_summary`; не влияют на verdict.
- **Promotion loop** — `pattern_library` + `pattern_promotion_candidates`; N≥5 проектов → human review → детерминированное правило → экономия токенов.
- **`last_seen_scan_id`** на `shown_findings` (edge) и `finding_aggregates` (master).
- **`llm_model` / `llm_backend` / `scanner_versions`** — в `scan_completed` для воспроизводимости и сравнения моделей.
- **Инварианты №1, №2, №4, fail-closed** — соблюдены.
- **MVP** = RSS-2…RSS-6 + RSS-9; promotion — отдельный этап.
- **Тестирование** — unit (детерминизм), контрактные, интеграция, E2E (подфаза 1C опционально), регрессия.

---

## 17. Ссылки

- ADR-0001 (fingerprint), ADR-0004 (master, event sourcing), ADR-0006 (gate matrix), ADR-0007 (per-branch), ADR-0008 (orchestrator modes), ADR-0009 (agent model)
- `docs/architecture.md` §3.1 (Tool Router), §3.5 (Storage), §4.1 (поток scan_diff), §8.1 (ruleset_hash)
- `orchestration/gate.py`, `storage/stores/*`, `server/tools/*`, `appsecgate-master/`, `git.py`

---

## 18. Изменения в `docs/adr/README.md`

```markdown
| ADR | Название | Статус |
|---|---|---|
| ADR-0001 | Fingerprint and semantic dedup | Accepted |
| ADR-0002 | Language consistency & agent fix reliability | Proposed |
| ADR-0003 | CI unresolved local delivery | Repurposed as classic hard-gate (ADR-0008) |
| ADR-0004 | Master server sync | Accepted (MS-1..7; MS-8 ⏸) |
| ADR-0005 | Project reconciliation & shown state machine | Accepted |
| ADR-0006 | Unified finding lifecycle model | Accepted |
| ADR-0007 | Per-branch state | Proposed (Фаза 3) |
| ADR-0008 | Orchestrator modes | Proposed |
| ADR-0009 | Agent implementation model | Proposed |
| ADR-0010 | RW-agent | Proposed (Пауза) |
| ADR-0011 | Scan run observability, passive counters, pattern promotion | Proposed (depends on ADR-0004/0007/0009) |
```