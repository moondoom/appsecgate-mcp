# ADR-0006: Unified finding lifecycle model

**Статус:** Accepted (PR-E, 2026-10-31)
**Дата:** 2026-10-31
**Файл:** `docs/adr/ADR-0006-unified-finding-lifecycle-model.md`
**Контекст:** Фаза 1 завершена (ADR-0005), Фаза 2 приостановлена (ADR-0003/ADR-0004); требуется единая модель жизненного цикла находки, не зависящая от контура (local / snapshot / master)
**Заменяет:** ADR-0003 §5.2 (таблица решений gate), ADR-0004 §5.3 (конфликт-резолюция)
**Связанные:** ADR-0001 (fingerprint), ADR-0005 (state machine `shown_findings`)

---

## 1. Термины

### 1.1. Идентификаторы

| Термин | Что | Где |
|---|---|---|
| `project_id` | Проект (T7/T9) | везде |
| `fingerprint` (`fp`) | PK находки (ADR-0001) | PK в `shown_findings` |
| `logical_id` | Семантический ID для кросс-схлопывания | `finding_identity` |
| `event_id` | UUID события в event-log | snapshot, master |
| `client_event_id` | UUID push-события на master (идемпотентность) | edge → master |

### 1.2. Координаты

| Термин | Что |
|---|---|
| `branch`, `commit` | Git-координаты на момент события |
| `first_seen_branch/commit` | Где впервые обнаружено |
| `last_seen_branch/commit` | Где последний positive-merge |
| `at`, `scanned_at` | UTC, ISO-8601 |
| `schema_version` | Версия формата события / snapshot |

### 1.3. Состояния жизненного цикла (`status`)

`SHOWN`, `POTENTIALLY_FIXED`, `FIXED`, `REOPENED`, `SUPPRESSED`, `WONT_FIX`.

**Активные** (влияют на negative-merge): `SHOWN`, `POTENTIALLY_FIXED`, `REOPENED`.
**Закрытые**: `FIXED`, `SUPPRESSED`, `WONT_FIX`.
**Терминальные** (до явного снятия): `SUPPRESSED` (до `suppression_expired` или `unsuppressed`), `WONT_FIX` (до `unsuppressed`; эмитент — `suppress_finding(action="unsuppress")`).

### 1.4. События (иммутабельные переходы)

| Событие | Триггер | Эмитент |
|---|---|---|
| `discovered` | positive-merge новой находки | scan |
| `reaffirmed` | positive-merge существующей | scan |
| `not_found_in_scope` | negative-merge (в охвате тула, та же ветка) | scan |
| `verify_fixed` | `verify_fix(reported=fixed)`, перескан: находки нет | verify_fix |
| `verify_not_fixed` | `verify_fix(reported=not_fixed)`, либо `reported=fixed`, но находка есть | verify_fix |
| `verify_wont_fix` | `verify_fix(reported=wont_fix)` | verify_fix |
| `suppressed` | `suppress_finding(scope)` | suppress_finding |
| `suppression_expired` | `expires_at` в прошлом (при чтении/скане) | internal |
| `unsuppressed` | явное снятие suppression/WONT_FIX (`suppress_finding(action="unsuppress")`) | suppress_finding |
| `reopened` | positive-merge поверх `FIXED` | scan |

### 1.5. Счётчики и таймстемпы

`scan_count` (positive-merge), `show_count` (`mark_shown`), `missed_scan_count` (negative-merge). Таймстемпы: `first_seen_at`, `last_seen_at`, `first_shown_at`, `last_shown_at`, `status_updated_at`, `fixed_at`, `suppressed_at`, `wont_fix_at`.

### 1.6. Источники истины

| Источник | Содержимое | Режим |
|---|---|---|
| Local SQLite | materialized state + `fix_attempts` | dev workstation |
| ~~Snapshot `.appsecgate-mcp/shown.ndjson`~~ | **event-log** (канал удалён решением владельца 2026-10-31, MS-6) | — |
| Master | event-log aggregate per `(project, fp)` | online, канон |

**Retention:** `SHOWN` / `POTENTIALLY_FIXED` / `REOPENED` **не истекают**; истекают только `FIXED` / `SUPPRESSED` / `WONT_FIX` по `status_updated_at + 30d`. Иначе `unresolved_local` тихо снимается — противоречие с killer-фичей.

### 1.7. Политики (конфиг, переопределяются через `config.yaml` / `APPSECGATE_*`)

| Ключ | Значения | Default |
|---|---|---|
| `gates.ci.block_on` | severities | `[critical, high]` |
| `gates.ci.wont_fix_action` | `skip` \| `block` \| `skip-if-same-branch` | **`skip-if-same-branch`** |
| `gates.ci.potentially_fixed_on_block_severity` | `block` \| `warn` | **`block`** |
| `gates.ci.new_finding_action` | `warn` \| `block` \| `info` | `warn` |
| `gates.ci.local_suppression_hides` | bool | `false` (двойной контур) |
| ~~`gates.ci.require_shown_snapshot`~~ | ~~bool~~ | ~~`false`~~ — **удалён** (MS-6, 2026-10-31): CI всегда master, fail-closed |

---

## 2. Карта жизненного цикла

### 2.1. Матрица переходов

| Prev ↓ / Event → | discovered | reaffirmed | not_found_in_scope | verify_fixed | verify_not_fixed | verify_wont_fix | suppressed | suppression_expired | unsuppressed | reopened |
|---|---|---|---|---|---|---|---|---|---|---|
| (none) | SHOWN | — | — | — | — | — | SUPPRESSED | — | — | — |
| SHOWN | — | SHOWN | POTENTIALLY_FIXED | — | SHOWN | WONT_FIX | SUPPRESSED | — | — | — |
| POTENTIALLY_FIXED | — | SHOWN | POTENTIALLY_FIXED | FIXED | POTENTIALLY_FIXED | WONT_FIX | SUPPRESSED | — | — | — |
| FIXED | — | REOPENED | FIXED | — | — | — | SUPPRESSED | — | — | — |
| REOPENED | — | REOPENED | POTENTIALLY_FIXED | FIXED | REOPENED | WONT_FIX | SUPPRESSED | — | — | — |
| SUPPRESSED | — | — | — | — | — | — | — | SHOWN | SHOWN | — |
| WONT_FIX | — | — | — | **no-op** | **no-op** | **no-op** | SUPPRESSED | — | SHOWN | — |

**Инварианты:**

- `not_found_in_scope` **не** применяется к `FIXED`, `SUPPRESSED`, `WONT_FIX`.
- `verify_*` на `WONT_FIX` — **no-op** (решение владельца 2026-10-31: снятие WONT_FIX — только через `unsuppressed` = `suppress_finding(action="unsuppress")`, чтобы не путать намерения).
- `SUPPRESSED → SHOWN` — только через `suppression_expired` (scope `ci`/`global`) или `unsuppressed` (`suppress_finding(action="unsuppress")`).
- Каждый переход обновляет `status_updated_at`.

### 2.2. Ортогональные измерения

| Измерение | Влияние на gate |
|---|---|
| `severity` | `ci_severity` — независимо от статуса |
| `suppression_scope` (`local`/`ci`/`global`) | `ci`/`global` скрывает; `local` — нет (двойной контур) |
| `suppression_expires_at` | истёкший `ci`/`global` не скрывает (эмитит `suppression_expired`) |
| `branch` | `unresolved_local` независим от ветки; negative-merge — только в своей |

### 2.3. Гейт-матрица (заменяет ADR-0003 §5.2)

| Условие | Действие | Reason | Конфиг |
|---|---|---|---|
| severity ∈ `block_on` | **block** | `ci_severity` | `gates.ci.block_on` |
| `SHOWN` | **block** | `unresolved_local` | хардкод |
| `REOPENED` | **block** | `reopened` | хардкод |
| `POTENTIALLY_FIXED` + severity ∈ `block_on` | **block** | `unconfirmed_fix_critical` | `gates.ci.potentially_fixed_on_block_severity` |
| `POTENTIALLY_FIXED` + severity ∉ `block_on` | **warn** | `unconfirmed_fix` | хардкод |
| `FIXED` | **skip** | — | хардкод |
| `SUPPRESSED` + scope `ci`/`global` + не истёк | **skip** | `suppressed` | хардкод |
| `SUPPRESSED` + scope `local` | **block** | `unresolved_local` | `gates.ci.local_suppression_hides` |
| `SUPPRESSED` + `ci`/`global` истёк | **block** | `unresolved_local` | хардкод |
| `WONT_FIX` + `last_seen_branch == CI-branch` | **skip** | `wont_fix` | `gates.ci.wont_fix_action=skip-if-same-branch` |
| `WONT_FIX` + `last_seen_branch != CI-branch` (вкл. `<unknown>`) | **block** | `wont_fix_other_branch` | то же |
| `WONT_FIX` (значение `skip`/`block`) | skip/block | `wont_fix` | `gates.ci.wont_fix_action` |
| (нет записи) | warn/info | `ci_new` | `gates.ci.new_finding_action` |

**Exit code:** `block` → `1`; `warn`/`skip`/`info` → `0`; инфраструктура → `2`.

**Правило `<unknown>`:** `branch="<unknown>"` **никогда** не равен CI-branch → при `skip-if-same-branch` всегда **block** (консервативно и детерминированно).

**Режим применения (ADR-0008):** в classic hard-gate (ADR-0008 §2.2) матрица **enforced** — exit 1 при `block`. В agent mode (ADR-0008 §2.1) — **advisory**: агент получает `GateSummary` через `check_gate` (ADR-0009 §3) и должен следовать, но LLM может отклониться.

---

## 3. Алгоритмы мерджа

### 3.1. Local merge (per scan)

```
for f in scan_result:
    if store.find(f.fp) is None: emit(discovered); store.create(SHOWN)
    else:                        emit(reaffirmed); store.positive_merge()
                                 # reset missed_scan_count; update last_seen_*

if branch != "<unknown>":
    for e in store.where(last_seen_branch == branch,
                         file_path in scan_scope,
                         status not in {FIXED, SUPPRESSED, WONT_FIX},
                         fp not in scan_result.fps):
        emit(not_found_in_scope); store.negative_merge()
else:
    # negative-merge запрещён; warning в meta.warnings
```

**Инварианты:** positive-merge — всегда; negative-merge — только в охвате и той же ветке; при `<unknown>` negative-merge запрещён.

### 3.2. `verify_fix` merge

```
reported = payload.reported_status
actual   = fp in scan_file(finding.file_path).fps

if current == WONT_FIX: no-op; return   # снятие — только suppress_finding(action="unsuppress")

match (reported, actual):
    (fixed,    False): emit(verify_fixed)     → FIXED   (fixed_confirmed_by='verify_fix')
    (fixed,    True ): emit(verify_not_fixed) → REOPENED
    (not_fixed, _   ): emit(verify_not_fixed) → без изменения статуса
    (wont_fix, _    ): emit(verify_wont_fix)  → WONT_FIX
```

**Явно:** «перескан нашёл» = `actual=True` (находка всё ещё есть). Это устраняет инверсию из ADR-0005 §2.9.

### 3.3. Snapshot merge (offline CI, event-log) — ~~актуален~~ **УДАЛЁН**

> Раздел исторический: snapshot-канал удалён решением владельца 2026-10-31
> (ADR-0004 MS-6). CI всегда тянет «показанное» с master (`GET /v1/findings`,
> §3.4), офлайн-снапшотов нет.

**Источники (было):** `.appsecgate-mcp/shown.ndjson` из `merge-base(base-ref, HEAD)` и из `HEAD`.

```
1. events_base = load(snapshot @ merge-base)
   events_head = load(snapshot @ HEAD)

2. append-only check:
   for fp in group_by_fp(events_base):
       missing = base[fp] - head[fp]
       for e in missing:
           if e.event not in {verify_fixed, verify_wont_fix, suppressed}:
               exit(1, reason=snapshot_regression, fp=fp, event=e)

3. replay per fp:
   for fp, evs in group_by_fp(events_head).items():
       state[fp] = fold(evs, matrix=§2.1, order=(at, event_id))

4. suppression_expired: если state=SUPPRESSED и expires_at < now → emit(suppression_expired) → SHOWN

5. apply gate matrix §2.3 to state
```

**Snapshot event:**

```json
{"schema_version":1,"event_id":"uuid","event":"verify_fixed",
 "project_id":"...","fp":"...","branch":"feature/x","commit":"abc123",
 "at":"2026-10-31T12:00:00Z","severity":"high",
 "suppression_scope":null,"suppression_expires_at":null,
 "missed_scan_count":3}
```

**Git:**

- `.gitattributes`: `.appsecgate-mcp/shown.ndjson merge=union`.
- После union — dedup по `event_id`, sort by `(at, event_id)`.
- `schema_version` mismatch → drop + warning (в духе ADR-0005 §2.7).

**Флаг `--require-shown-snapshot`:** при отсутствии snapshot → `exit 2` (инфраструктура), не `exit 1`.

### 3.4. Master merge (event sourcing, заменяет ADR-0004 §5.3)

**Приём:**

1. Дедуп по `client_event_id`.
2. Валидация `schema_version`, redaction (инвариант №4).
3. Append в `audit_log` (append-only, без UPDATE/DELETE).
4. Агрегация per `(project, fp)` по §2.1.

**Конфликт-резолюция:**

| # | Правило |
|---|---|
| 1 | `verify_fixed` побеждает `not_found_in_scope` / `reaffirmed`, если `last_seen_commit` новее **в том же branch** |
| 2 | `reopened` побеждает `FIXED`, если `last_seen_commit` новее **в том же branch** |
| 3 | `suppressed(ci/global)` побеждает всё, кроме `reopened` после него (новый цикл) |
| 4 | `suppressed(local)` хранится как событие, но **не влияет** на CI-вердикт |
| 5 | LWW по `at` (UTC) + tie-break по `event_id` |
| 6 | `WONT_FIX` терминален до `unsuppressed` (`suppress_finding(action="unsuppress")`) |

### 3.5. Cross-source consistency

| Направление | Кто | Что |
|---|---|---|
| ~~local → snapshot~~ | — | **удалено MS-6**: snapshot-канала нет |
| local → master | edge `sync` | push event (`client_event_id`) |
| master → local | edge `pull` | `ci`/`global` suppressions + config |
| ~~snapshot → CI~~ | — | **удалено MS-6**: CI всегда тянет с master (ADR-0008 §7) |
| master → CI | CI | `GET /v1/findings` → gate |

**Контрактный инвариант:** master-aggregate per `(project, fp)` — единственный источник
истины для CI; локальный state с ним не рассинхронизируется через push/pull
(ADR-0004). Тест `test_snapshot_master_parity` живёт в **master-пакете** и проверяет
event-log агрегат, а не файл snapshot.

---

## 4. Последствия

### 4.1. Влияние на ADR-0003

- **§5.1 (CLI)** — остаётся как **classic hard-gate** (ADR-0008 §2.2): CI всегда тянет «показанное» с master (`GET /v1/findings`, fail-closed exit 2); `--base-ref` через merge-base, warn не влияет на exit code.
- **§5.2** — заменена §2.3 этого ADR.
- **§5.3 / §6 (snapshot)** — **удалено MS-6** (решение владельца 2026-10-31), историческое.
- **Статус ADR-0003:** **`Repurposed as classic hard-gate`** (ADR-0008), не «Partially superseded».

### 4.2. Влияние на ADR-0004

- **§5.1** — события расширяются: `not_found_in_scope`, `suppressed`, `suppression_expired`, `verify_wont_fix`, `reopened`; во все `finding_*` — `first_seen_branch/commit`, `last_seen_branch/commit`, `missed_scan_count`.
- **§5.3** — заменена §3.4 этого ADR.
- **§6** — CI всегда `master` (ADR-0004 §6, решение владельца 2026-10-31): `GET /v1/findings`, fail-closed; snapshot-канал удалён; `--shown-source {master, local}` (ADR-0008 §7).
- **§5.2 (API)** — расширяется `GET /v1/findings?branch=&commit=` (ADR-0008 §5).
- **Статус:** `Paused (superseded in parts by ADR-0006)`.

### 4.3. Влияние на ADR-0005

- §2.6 (гейт) — заменена §2.3 этого ADR (расширение: конфиг-ключи, `<unknown>` → block).
- §2.9 (маппинг verify_fix) — уточнена §3.2 (явно через `actual`, no-op для `WONT_FIX`).
- §2.12 (snapshot) — расширена §3.3 (event-log).
- §2.2 (state machine) — дополнена `suppression_expired`, `unsuppressed`.

### 4.4. Файлы для изменения

- `orchestration/gate.py` — матрица §2.3, конфиг-ключи §1.7, `branch`/`<unknown>`.
- `server/tools/verify_fix.py` — §3.2.
- `server/tools/suppress.py` — `action: suppress|unsuppress`, emit(`unsuppressed`); `suppression_expired` при чтении.
- `storage/stores/shown.py` — `suppression_expired`, `WONT_FIX` no-op.
- `server/ci.py` — CLI `ci`: master-параметры (`--master-url`/`--api-key`/`--project-id`), fail-closed exit 2 (ADR-0004 MS-6).
- `git.py` — `merge-base`, branch/commit.
- `config/models.py` — новые ключи §1.7.
- `docs/adr/README.md` — статусы ADR-0003/0004/0006.
- `docs/architecture.md` — §3.5 (схема), §4.1 (поток).

### 4.5. Влияние на тесты

- `test_status_matrix` — каждый переход §2.1.
- `test_gate_matrix` — каждый ряд §2.3, включая `WONT_FIX` + same/other/`<unknown>` branch.
- `test_verify_fix_no_inversion` — `fixed` + actual=True → `REOPENED`; `fixed` + actual=False → `FIXED`.
- `test_verify_fix_wont_fix_noop`.
- `test_suppression_expired_ci_global`, `test_suppression_expired_local_is_noop`.
- `test_retention_unresolved_does_not_expire`.
- ~~`test_snapshot_append_only_violation`~~ — **удалён MS-6** (snapshot-канал).
- ~~`test_snapshot_schema_mismatch`~~ — **удалён MS-6** (snapshot-канал).
- `test_snapshot_master_parity` — остаётся в **master-пакете** (про event-log агрегат, не про файл snapshot).
- `test_gate_unknown_branch_blocks`.

---

## 5. Открытые вопросы и ограничения

1. **`schema_version` bump** — правило: несовпадение → drop + warning (в духе ADR-0005 §2.7). При добавлении полей — bump.
2. **`skip-if-same-branch` при `<unknown>`** — закрыто (block, §2.3).
3. **Консолидация тулов.** `suppress_finding` уже покрывает `wont_fix` через `scope=wont_fix`; консолидация с `verify_fix` — не в Фазе 2. Модель готова: `WONT_FIX` — first-class статус, не атрибут `fix_attempts`.
4. **Known limitations:**
   - **Multi-version (per-branch state)** — запланировано в **ADR-0007** (Фаза 3); до реализации classic с несколькими ветвями не поддерживается.
   - **Orchestrator-пресеты** — **ADR-0008** (есть); блокер Фазы 2 снят.
   - **RW-orchestrator** — **ADR-0010** (Пауза); каркас в ADR-0009 §7.
   - **Офлайн-CI** — **не поддерживается** после MS-6; master обязателен.
   - **Agent mode policy advisory** — для enforced gate использовать classic hard-gate (ADR-0008 §2.2).
   - `verified_since_last_scan` — отдельный PR.

---

## 6. План внедрения

| # | Содержание | Зависит |
|---|---|---|
| **SM-1** ✅ | Матрица §2.1 + `suppression_expired` + `unsuppressed` через `suppress_finding(action=...)` + `test_status_matrix` + `test_unsuppress_via_suppress_finding` | — |
| **SM-2** ✅ | Гейт-матрица §2.3 + конфиг-ключи §1.7 + `test_gate_matrix` | SM-1 |
| **SM-3** ✅ | `verify_fix` merge (§3.2), no-op для `WONT_FIX`, `test_verify_fix_no_inversion` | SM-1 |
| **SM-4** ⛔ | ~~Snapshot event-log (§3.3)~~ — **superseded by MS-6** (snapshot удалён) | SM-1 |
| **SM-5** ✅ | Master merge (§3.4) — **выполнен в MS-2..5** (ADR-0004); `test_snapshot_master_parity` в master-пакете остаётся (это про event-log агрегат, не про файл snapshot) | ~~SM-4~~ |
| **SM-6** ✅ | Документация: ADR-0006, статусы в `docs/adr/README.md`, `architecture.md` | SM-1..5 |

---

## 7. Принятые решения (Q1–Q12)

| # | Вопрос | Решение |
|---|---|---|
| Q1 | `wont_fix_action` | **`skip-if-same-branch`** (default), переопределяется конфигом; `<unknown>` → block |
| Q2 | `potentially_fixed_on_block_severity` | **`block`** (default), переопределяется конфигом; severity-гейт не ослабляем |
| Q3 | `SUPPRESSED` + scope `local` в CI | **block** (`unresolved_local`) — двойной контур |
| Q4 | `verify_fix` на `WONT_FIX` | **no-op**; снятие — только `unsuppressed` (`suppress_finding(action="unsuppress")`) |
| Q5 | `suppressed(local)` в snapshot | **да**, для аудита; CI игнорирует по `suppression_scope` |
| Q6 | Формат snapshot | **event-log**, `schema_version=1` |
| Q7 | Retention | 30d только для `FIXED`/`SUPPRESSED`/`WONT_FIX`; `SHOWN`/`POTENTIALLY_FIXED`/`REOPENED` не истекают |
| Q8 | Консолидация тулов | future work; модель готова (`WONT_FIX` first-class) |
| Q9 | Интерфейс `unsuppressed` | расширение `suppress_finding(action)`; новый тул не создаём |
| Q10 | Policy в agent mode | **Advisory**; enforced — classic hard-gate (ADR-0008) |
| Q11 | Per-branch state | **ADR-0007** (Фаза 3); Фаза 2 — глобальный PK |
| Q12 | Snapshot-канал | **Удалён MS-6**; master — единственный источник истины |

---

## 8. Итог

- Единая модель **жизненного цикла находки** для local / master; гейт-логика и конфликт-резолюция — в одном месте.
- Snapshot **удалён MS-6**; master — единственный источник истины. Офлайн-CI не поддерживается (ограничение Фазы 2).
- Два режима оркестрации (ADR-0008): agent mode (advisory) и classic hard-gate (enforced).
- `verify_fix` явный (через `actual`), no-op для `WONT_FIX`; снятие `WONT_FIX`/`SUPPRESSED` — через `suppress_finding(action="unsuppress")` или `suppression_expired`.
- Retention не снимает `unresolved_local`; `<unknown>` branch консервативно блокирует.
- Конфиг-ключи покрывают спорные случаи (`wont_fix_action`, `potentially_fixed_on_block_severity`), defaults — безопасные.
- ADR-0003/ADR-0004 → `Paused (superseded in parts by ADR-0006)`; ADR-0005 дополняется, не отменяется.

---

## 9. Ссылки

- ADR-0001 (fingerprint & dedup), ADR-0005 (state machine `shown_findings`)
- ADR-0003 (CI-контур — Repurposed as classic hard-gate, ADR-0008), ADR-0004 (master — Paused, superseded in parts by ADR-0006)
- ADR-0007 (per-branch state), ADR-0008 (orchestrator modes), ADR-0009 (agent implementation), ADR-0010 (RW-agent — Пауза)
- `docs/architecture.md` §3.5, §4.1, §8, §9.5
- `orchestration/gate.py`, `server/ci.py`, `storage/stores/shown.py`, `server/tools/verify_fix.py`, `server/tools/suppress.py`, `git.py`

---

## 10. Изменения в `docs/adr/README.md`

```markdown
| ADR | Название | Статус |
|---|---|---|
| ADR-0001 | Fingerprint and semantic dedup | Accepted |
| ADR-0003 | CI unresolved local delivery | Paused (superseded in parts by ADR-0006) |
| ADR-0004 | Master server sync | Paused (superseded in parts by ADR-0006) |
| ADR-0005 | Project reconciliation & shown state machine | Accepted (дополнен ADR-0006) |
| ADR-0006 | Unified finding lifecycle model | Proposed (→ Accepted после мержа PR-E) |
| ADR-0007 | Per-branch state | Proposed (Фаза 3) |
| ADR-0008 | Orchestrator presets | Proposed (блокер Фазы 2) |
```