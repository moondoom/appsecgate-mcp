# ADR-0005: `scan_project` как reconciliation-инструмент и state machine `shown_findings`

- **Статус:** Accepted
- **Дата:** 2026-10-31
- **Контекст:** T8 (`open-tasks.md`), уточнение владельца 2026-10-31, ревью агента 2026-10-31
- **Связанные:** ADR-0001 (fingerprint & dedup). ADR-0003 и ADR-0004 — **неактивны** (перерабатываются, см. §3.3); ADR-0005 на них не опирается как на источники истины.

---

## 1. Контекст

В `architecture.md` §3.1 и `open-tasks.md` T8 `scan_project` был описан как **announce-only**: «обзор» с TOP-N, без семантики персиста. По факту реализация пишет все найденные находки в `shown_findings`. Расхождение доков и кода — источник неопределённости:

- неясно, означает ли `SHOWN` «показано агенту» или «обнаружено сканером»;
- логика gate опирается на `was_shown()`, но не различает «показано и проигнорировано» от «показано и подтверждено фикс»;
- `scan_diff` / `scan_file` / `scan_project` имеют разный охват, но документация не фиксирует, кто и какие negative-переходы делает.

Уточнение владельца (2026-10-31): `scan_project` — **основной инструмент полной сверки (scan + merge + report)**, а не «обзор». TOP-10 — UX-срез для агента, а не граница семантики. `scan_diff` — основной инструмент локальной работы; `scan_file` — точечный. Каждый из трёх имеет право на negative-merge, но в своей зоне ответственности.

---

## 2. Решение

### 2.1. Роли инструментов

| Тул | Роль | Охват | Negative-merge |
|---|---|---|---|
| `scan_project()` | Полная сверка (reconcile) | весь проект, без аргументов | глобальный, **по всей текущей ветке** (файловый список не нужен) |
| `scan_diff()` | Локальная работа над изменениями | added + modified + **deleted** + renamed (старый путь) | **scoped**: только находки в затронутых файлах |
| `scan_file(path)` | Точечная проверка / `verify_fix` | один файл | **scoped**: только находки этого файла |

Positive-merge (найдено → обновить `last_seen_at`, `last_seen_branch`, `last_seen_commit`, `scan_count++`) выполняется одинаково во всех тулах и не зависит от типа скана.

Negative-merge (не найдено → `POTENTIALLY_FIXED`, `missed_scan_count++`) выполняется только для находок, попадающих в охват тула, и только для находок **той же ветки** (см. §2.4).

### 2.2. State machine `shown_findings.status`

Статусы: `SHOWN`, `POTENTIALLY_FIXED`, `FIXED`, `REOPENED`, `SUPPRESSED`, `WONT_FIX`.

Positive-переходы (найден):

| Prev | Next | Примечание |
|---|---|---|
| (нет) | `SHOWN` | новая находка |
| `SHOWN` | `SHOWN` | reaffirmed, `missed_scan_count=0` |
| `POTENTIALLY_FIXED` | `SHOWN` | ложная тревога — вернулась |
| `FIXED` | `REOPENED` | регрессия (сейчас в коде не реализовано, К4) |
| `REOPENED` | `REOPENED` | reaffirmed |
| `SUPPRESSED` | `SUPPRESSED` | filtered до показа; статус не меняется |
| `WONT_FIX` | `WONT_FIX` | осознанно принятый риск; не спамим |

Negative-переходы (не найден в охвате, та же ветка):

| Prev | Next | Примечание |
|---|---|---|
| `SHOWN` | `POTENTIALLY_FIXED`, `missed_scan_count=1` | |
| `POTENTIALLY_FIXED` | `POTENTIALLY_FIXED`, `missed_scan_count++` | авто-перехода в `FIXED` **нет** |
| `REOPENED` | `POTENTIALLY_FIXED`, `missed_scan_count=1` | |
| `FIXED` | `FIXED` | не трогаем |
| `SUPPRESSED` | `SUPPRESSED` | не трогаем |
| `WONT_FIX` | `WONT_FIX` | не трогаем |

Negative-переходы для находок **вне охвата** (файл не в diff, не тот файл, другая ветка) — **не выполняются**, статус сохраняется.

Специальные случаи:

- **deleted-файл в diff:** только находки в **активных** статусах (`SHOWN`, `POTENTIALLY_FIXED`, `REOPENED`) → `POTENTIALLY_FIXED` (`missed_scan_count=1`). `FIXED`, `SUPPRESSED`, `WONT_FIX` — не трогаем (К7).
- **renamed-файл:** `logical_id` включает `file_path` (ADR-0001), поэтому при rename образуется **новый** `logical_id`. Старый путь → `POTENTIALLY_FIXED` (если старый файл удалён), новый путь → новая запись с новым fingerprint. Автоматического кросс-схлопывания нет; возможно только семантическим dedup (`deduplicate_families`), не гарантируется (К8).
- **`missed_scan_count`** — информационное поле. Не триггерит авто-переход и не влияет на gate. Используется в отчётах и для отладки «прыгающих» находок.
- **`SUPPRESSED`-находки** не доходят до store при сканировании (пайплайн фильтрует suppression до persist). Записи `SUPPRESSED` создаются тулом `suppress_finding`; `SUPPRESSED → SUPPRESSED` в store не происходит в ходе скана. Для `counts.suppressed` в отчёте считаем находки, отфильтрованные на этапах suppression в этом скане (К6).

Каждый переход статуса обновляет **`status_updated_at = now()`**.

### 2.3. Подтверждение фикса

Переход `POTENTIALLY_FIXED → FIXED` выполняется **только** явным `verify_fix`. Ответ `verified_status=fixed` → `FIXED`, `fixed_confirmed_by='verify_fix'`.

Счётчик `missed_scan_count` растёт при каждом negative-merge, но **не является условием** перехода в `FIXED`. Избегаем «мигания» при нестабильных сканерах, сохраняем явность подтверждения.

### 2.4. Branch / commit

Каждая находка хранит:
- `first_seen_branch`, `first_seen_commit` — при первом обнаружении;
- `last_seen_branch`, `last_seen_commit` — при каждом positive-merge.

**Negative-merge ограничен текущей веткой.** `scan_project` на `feature/x` не переводит в `POTENTIALLY_FIXED` находки, обнаруженные только на `main`. Фильтр: `last_seen_branch == текущая ветка`.

Если git-контекст недоступен (не репозиторий), `branch = "<unknown>"`; negative-merge выполняется только по совпадению `project_id`, с предупреждением в `meta.warnings` (К10).

Git-контекст получаем через `git rev-parse --abbrev-ref HEAD` и `git rev-parse HEAD` (в `git.py`).

### 2.5. Контракт `scan_project`

```jsonc
{
  "status": "ok",
  "counts": {
    "new": 4, "reaffirmed": 12, "reopened": 1,
    "potentially_fixed": 19, "suppressed": 3
  },
  "top_findings": [ /* TOP-10 по severity, формат Finding (T15) */ ],
  "requires_confirmation": {
    "finding_ids": ["a1b2c3d4e5f60718", "..."],   // ≤ 25 fingerprint
    "total_potentially_fixed": 19,
    "truncated": false
  },
  "suggested_action": "run verify_fix_batch on requires_confirmation.finding_ids",
  "meta": {
    "branch": "feature/x", "commit": "abc1234...",
    "scanned_at": "2026-10-31T...",
    "scanners": ["semgrep", "gitleaks", "trivy"],
    "warnings": []
  }
}
```

- Аргументов у `scan_project` **нет** (Q4, breaking change — приемлемо в pre-1.0.0).
- `requires_confirmation.finding_ids` — **limited to 25**: все актуальные `POTENTIALLY_FIXED` проекта/ветки после merge, сортировка `severity desc → last_seen_at desc`; при превышении `truncated=true`, полный список — через `query_findings_db(status=POTENTIALLY_FIXED)` (К18).
- `finding_ids` — fingerprint'ы; агенту достаточно их для `verify_fix_batch`.
- **`confirmed_fixed` убран из counts** (К17): скан — событие обнаружения, `verify_fix` — событие подтверждения, это разные временные оси. При необходимости прогресс-метрики добавить отдельным полем `verified_since_last_scan` в отдельном PR с явной семантикой «временное окно между сканами».
- `suggested_action` заменяет `next_actions` (К19).
- Старый announce-формат (`by_file_top10`, `next_actions`, `truncated`, `total_available`) заменяется полностью (К19).

### 2.6. CI-гейт

`GateEngine.evaluate` в режиме CI:

| Статус в `shown_findings` | Действие |
|---|---|
| (нет записи) | блок по severity (как сейчас) |
| `SHOWN` | **block**, reason=`unresolved_local` |
| `REOPENED` | **block**, reason=`reopened` |
| `POTENTIALLY_FIXED` | **warn**, reason=`unconfirmed_fix` |
| `FIXED` | пропуск |
| `SUPPRESSED` | пропуск |
| `WONT_FIX` | **пропуск**, reason=`wont_fix` |

`unresolved_local` срабатывает **независимо от ветки**, на которой находка была показана. В сообщении CI указываются `first_seen_branch` / `last_seen_branch` (К12).

`WONT_FIX` **не блокирует**: разработчик явно зафиксировал «не чинить» — это отличается от `SHOWN` («видел, но не отреагировал»). Информация попадает в отчёт CI (`wont_fix_count`), но не в блокирующий набор.

### 2.7. Schema version

Во всех трёх БД (`shown_findings.db`, `feedback.db`, `scan_cache.db`):

```sql
CREATE TABLE schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL          -- 'schema_version' -> '1'
);
```

При старте: чтение `schema_version`. Не совпала или отсутствует → **drop + recreate + warning в лог**. Pre-1.0.0 миграций нет; при 1.0.0 ввести миграции поверх этого механизма.

**Технические детали drop (К15):**
1. `PRAGMA foreign_keys=OFF`.
2. `DROP VIEW` всех views (в `shown_findings.db` — 5 views).
3. `DROP TABLE` всех таблиц, включая `sqlite_sequence` (AUTOINCREMENT в `fix_attempts`, `feedback`).
4. Пересоздание схемы.
5. Проставить `schema_version='1'`.
6. Всё — в одной транзакции.

Точка вызова — `init_databases()` (`db.py`), чтобы тесты, создающие store вручную, не ломались: свежая БД = версия проставляется без дропа.

### 2.8. Схема `shown_findings`

`logical_id` **не хранится** в `shown_findings` (К1). Все потребители (`verify_fix`, `v_findings`, `v_verification_coverage`, `ShownFindingsStore.find()`, `export_snapshot`, `finding_context`) переходят на джойн через `finding_identity` по fingerprint.

```sql
CREATE TABLE shown_findings (
    fingerprint          TEXT PRIMARY KEY,
    project_id           TEXT NOT NULL,       -- T7, T9
    rule_id              TEXT NOT NULL,
    file_path            TEXT NOT NULL,
    severity             TEXT NOT NULL,
    scanner              TEXT NOT NULL,
    category             TEXT NOT NULL,

    status               TEXT NOT NULL,       -- SHOWN | POTENTIALLY_FIXED | FIXED | REOPENED | SUPPRESSED | WONT_FIX
    status_updated_at    TIMESTAMP NOT NULL,  -- аудит переходов
    missed_scan_count    INTEGER NOT NULL DEFAULT 0,

    first_seen_branch    TEXT,
    first_seen_commit    TEXT,
    last_seen_branch     TEXT,
    last_seen_commit     TEXT,

    first_shown_at       TIMESTAMP,           -- nullable: заполняется mark_shown()
    last_shown_at        TIMESTAMP,
    show_count           INTEGER NOT NULL DEFAULT 0,

    first_seen_at        TIMESTAMP NOT NULL,  -- факт обнаружения (positive-merge)
    last_seen_at         TIMESTAMP NOT NULL,
    scan_count           INTEGER NOT NULL DEFAULT 1,

    fixed_at             TIMESTAMP,
    fixed_confirmed_by   TEXT,                -- 'verify_fix' | NULL

    suppressed_at        TIMESTAMP,
    suppress_reason      TEXT,

    wont_fix_at          TIMESTAMP,
    wont_fix_reason      TEXT
);

CREATE INDEX idx_shown_project_status ON shown_findings(project_id, status);
CREATE INDEX idx_shown_project_file   ON shown_findings(project_id, file_path);
CREATE INDEX idx_shown_last_seen      ON shown_findings(last_seen_at);
```

**Разделение `*_seen_*` и `*_shown_*`** (К3):
- `first_seen_at` / `last_seen_at` / `scan_count++` — при **каждом факте обнаружения** сканером (positive-merge).
- `first_shown_at` / `last_shown_at` / `show_count++` — только когда находка **реально попала в ответ агенту** (TOP-10 у `scan_project`, весь ответ у `scan_file` / `scan_diff`).

Добавляется шаг **`mark_shown(fingerprints)`** после формирования ответа тула.

`WONT_FIX` — полноценный статус (не только в `fix_attempts`): гейту нужен источник истины в одном месте, иначе потребуется JOIN с `fix_attempts` на каждой находке в CI. Параллельно `verify_fix(wont_fix)` пишет attempt в `fix_attempts` (для `get_scan_history`).

### 2.9. Маппинг `verify_fix → status`

| `verify_fix` вызов | `verified_status` в ответе | Переход в `shown_findings` |
|---|---|---|
| `reported_status=fixed` + перескан нашёл | `fixed` | `→ FIXED`, `fixed_at=now()`, `fixed_confirmed_by='verify_fix'` |
| `reported_status=fixed` + перескан не нашёл | `not_fixed` | `→ REOPENED` |
| `reported_status=not_fixed` | `not_fixed` | остаётся как было (`SHOWN` / `POTENTIALLY_FIXED` / `REOPENED`) |
| `reported_status=wont_fix` (без перескана) | `wont_fix` | `→ WONT_FIX`, `wont_fix_at=now()`, `wont_fix_reason=...` |

Матчинг находки внутри `verify_fix` — **по fingerprint**; при «прыжке» fingerprint — через `finding_identity` по `logical_id` (К1). `verify_fix_batch` принимает `finding_ids` (fingerprint'ы из `requires_confirmation`).

### 2.10. Views и query (К20, К22)

- `v_findings`, `v_summary`, `v_verification_coverage` — джойн **по fingerprint** через `finding_identity`.
- `v_summary` дополняется `POTENTIALLY_FIXED` / `REOPENED`.
- `query_findings_db(status='POTENTIALLY_FIXED')` работает.
- `is_unresolved()` — **удалить** (не вызывается, семантику задаёт gate-таблица §2.6).

### 2.11. `get_scan_history` (К21)

- Счётчики `wont_fix` — по `fix_attempts` (`verified_status='WONT_FIX'`).
- В items добавить `missed_scan_count` и ветки (`first_seen_branch` / `last_seen_branch`).

### 2.12. Snapshot (К13)

Поле `status` в snapshot (`shown.ndjson`) — **опциональное**. При отсутствии считаем запись `SHOWN` (текущее поведение block unresolved_local). Механику snapshot не расширяем: она будет переработана вместе с ADR-0003.

### 2.13. Git integration (К11)

Добавляется `git_changed_with_status()` в `git.py`:

- `git diff --name-status -z` (или `git status --porcelain -z` для staged+unstaged+untracked).
- Статусы: `A` (added), `M` (modified), `D` (deleted), `R` (renamed, оба пути).
- Deleted-файлы идут в negative-merge (§2.2, К7); из скана исключаются.
- Renamed: старый путь → `POTENTIALLY_FIXED`; новый путь — новый fingerprint.

---

## 3. Последствия

### 3.1. Breaking changes (pre-1.0.0, приемлемо)

- `scan_project(path)` → ошибка валидации Pydantic; аргумент удалён.
- Схема `shown_findings` меняется → старые БД дропаются при первом запуске (§2.7).
- Старый announce-формат (`by_file_top10`, `next_actions`, `truncated`, `total_available`) заменён контрактом §2.5.
- Документация (`README`, `README.ru.md`, `llms.txt`, `docs/deploy-agents.md`) обновляется в PR-E.

### 3.2. Файлы для изменения

- `storage/db.py` — `init_databases()`, `schema_meta`, drop-on-mismatch.
- `storage/migrations/` (новое) — реализация §2.7.
- `storage/stores/shown.py` — новая схема, state machine, branch/commit, `mark_shown()`.
- `storage/views/` — переделка джойнов на `finding_identity` (§2.10).
- `normalization/dedup.py` — без изменений (T10 закрыт).
- `orchestration/coordinator.py` — positive/negative-merge, scoped negative-merge (§2.1–2.2).
- `server/tools/scan.py` — `scan_project()` без аргументов, новый формат (§2.5), `mark_shown()`.
- `server/tools/verify_fix.py` — маппинг §2.9, матчинг по fingerprint + finding_identity.
- `orchestration/gate.py` — таблица §2.6, `GateDecision` с branch-info.
- `server/output.py` — `_build_announce_output` → `_build_project_report`.
- `git.py` — `git_changed_with_status()`, `rev-parse`.
- `server/tools/history.py` — §2.11.
- `server/tools/query.py` — §2.10.
- `docs/architecture.md` — §3.1, §3.5, §4.1.
- `docs/deploy-agents.md` — нет аргументов у `scan_project`.
- `AGENTS.md` — см. §3.6.

### 3.3. Влияние на другие ADR (К23)

- **ADR-0001** — без изменений; fingerprint остаётся ключом, `logical_id` — в `finding_identity`.
- **ADR-0003** и **ADR-0004** — по решению владельца **неактивны** (перерабатываются, до возврата к Фазе 2). В `docs/adr/README.md` помечаются «Неактивен (перерабатывается)». Уже реализованные части ADR-0003 (`appsecgate ci`, snapshot) **не расширяем и не удаляем**; примечание в `AGENTS.md`.
- ADR-0005 не опирается на ADR-0003/0004 как на источники истины; уже реализованные механизмы (snapshot, `appsecgate ci`) продолжают работать как есть.

### 3.4. Влияние на тесты

Новые сценарии (T14, третья итерация):
- `scan_project` дважды без изменений → все `SHOWN`, `scan_count=2`, `missed_scan_count=0`.
- правка файла → `scan_project` → `POTENTIALLY_FIXED`, `requires_confirmation` содержит fingerprint.
- `verify_fix(fixed)` → `FIXED`, `fixed_confirmed_by='verify_fix'`.
- регрессия: удалить фикс → `scan_project` → `REOPENED` (К4).
- `scan_diff` на файле вне diff → статусы других файлов не меняются.
- `scan_project` на `feature/x` не трогает находки, видимые только на `main`.
- переименование файла: старый путь → `POTENTIALLY_FIXED`, новый — новый fingerprint (К8).
- deleted-файл: активные статусы → `POTENTIALLY_FIXED`, `FIXED`/`SUPPRESSED`/`WONT_FIX` не тронуты (К7).
- schema mismatch → drop + warning в лог (К15).

Юнит-тесты:
- `test_shown_state_machine.py` — все переходы §2.2.
- `test_shown_state_machine_wont_fix_stays`.
- `test_verify_fix_wont_fix_mapping`, `test_verify_fix_not_fixed_maps_to_reopened`.
- `test_status_updated_at_on_every_transition`.
- `test_scan_project_no_args`.
- `test_gate_potentially_fixed_is_warn`, `test_gate_wont_fix_is_skip`.
- `test_mark_shown_separate_from_seen`.
- `test_finding_identity_join_in_views`.
- `test_git_changed_with_status` (A/M/D/R).
- `test_drop_on_schema_mismatch` (все 3 БД, views + sqlite_sequence).

### 3.5. Разбиение на PR (К24)

| PR | Содержание | Зависимости |
|---|---|---|
| **A** | `schema_meta` + drop-on-mismatch (К14/К15) | — |
| **B1** | Рефакторинг потребителей на `finding_identity` (К1): `verify_fix`, views, `find()`, `finding_context`, `export_snapshot`. Без смены поведения, все существующие тесты зелёные | A |
| **B2** | State machine (§2.2) + `WONT_FIX`-статус + branch/commit + `missed_scan_count` + scoped negative-merge + маппинг `verify_fix → status` (§2.9) | B1 |
| **C** | `scan_project()` без аргументов + новый формат (§2.5, без `confirmed_fixed`) + лимит 25 + `suggested_action` + `mark_shown()` | B2 |
| **D** | Gate: `POTENTIALLY_FIXED → warn`, `WONT_FIX → skip`, branch-info в `GateDecision` | B2 |
| **E** | T14-сценарии + `docs/` + `AGENTS.md` + breaking-change документация | A, B1, B2, C, D |

PR-A независим; PR-D независим от C. `make check` зелёный на каждом шаге.

### 3.6. AGENTS.md (К14)

Уточнение правила: ручной дроп `shown_findings` / `suppressions` / `feedback` в фичах запрещён; **автоматический** drop — только штатный механизм `schema_meta` при старте (пересоздание по схеме из ADR-0005 / `architecture.md`).

---

## 4. Открытые вопросы (вне ADR)

1. **Синхронизация branch/commit с master** — при возобновлении ADR-0004 учесть поля `first_seen_branch/commit`, `last_seen_branch/commit` в событиях.
2. **Reconciliation при отсутствии git** (`branch="<unknown>"`) — допустимый fallback по `project_id`, в будущем можно ограничить `scan_project` требованием git-контекста.
3. **`requires_confirmation` лимит 25** — константа этого релиза; при необходимости вынести в `config.gates.ci.requires_confirmation_limit` в отдельной задаче.
4. **`verified_since_last_scan`** — если понадобится прогресс-метрика после беты, добавить отдельным PR с явной семантикой временного окна между сканами (не смешивать с scan-counts; К17).

---

## 5. Итог

- `scan_project` = reconciliation-инструмент; persist всех находок, TOP-10 — UX.
- State machine формализован: `SHOWN` / `POTENTIALLY_FIXED` / `FIXED` / `REOPENED` / `SUPPRESSED` / `WONT_FIX`.
- Negative-merge scoped по охвату тула и по текущей ветке.
- `POTENTIALLY_FIXED` **не блокирует** CI (warn `unconfirmed_fix`); `WONT_FIX` **пропускается** (reason `wont_fix`).
- Подтверждение фикса — только явный `verify_fix`.
- Branch/commit фиксируются на каждой находке; `git_changed_with_status()` даёт статусы A/M/D/R.
- `logical_id` живёт в `finding_identity`; `shown_findings` джойнит по fingerprint.
- `schema_version` + drop-on-mismatch до 1.0.0 (с учётом views и `sqlite_sequence`).
- `scan_project()` без аргументов; `scan_diff` — основной локальный инструмент; `scan_file` — точечный.
- `confirmed_fixed` убран из counts; `suggested_action` заменяет `next_actions`.
- ADR-0003 / ADR-0004 — неактивны (перерабатываются), ADR-0005 на них не опирается как на источники истины.