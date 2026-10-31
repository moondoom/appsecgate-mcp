# ADR-0007: Per-branch state

**Статус:** Proposed (Фаза 3; не блокирует Фазу 2)
**Дата:** 2026-10-31
**Файл:** `docs/adr/ADR-0007-per-branch-state.md`
**Контекст:** ADR-0006 §5.5 зафиксировал known limitation: classic с несколькими поддерживаемыми версиями (`release/1.x`, `release/2.x`) не поддерживается. `PRIMARY KEY fingerprint` → состояние глобально на проект. Требуется per-branch модель.
**Связанные:** ADR-0001 (fingerprint), ADR-0005 (state machine), ADR-0006 (lifecycle), ADR-0008 (orchestrator modes)

---

## 1. Контекст

- `shown_findings.PRIMARY KEY fingerprint` → одно состояние на `(project, fingerprint)`.
- Следствия:
  - Фикс на `main` → `FIXED` глобально → скан `release/1.x` (где фикса нет) → `REOPENED` → релизный CI блокируется. Корректно по смыслу, но шумно.
  - Фикс на `release/1.x` → `FIXED` глобально → `main` CI молчит, пока не смержено. **Опасно:** дыра на `main` не видна.
- В ADR-0006 §3.4 правила 1–2 уже оперируют «в том же branch», но PK — глобальный. Это несогласованность.
- Владелец (2026-10-31): multi-version — Фаза 3; для Фазы 2 — known limitation.

**Вывод:** нужна per-branch модель, чтобы classic-сценарий с несколькими версиями работал без ложных `REOPENED` и без «слепых зон» на `main`.

---

## 2. Решение

**Per-branch state:** состояние находки — функция `(project_id, branch, fingerprint)`.

### 2.1. Schema

```sql
-- было: PRIMARY KEY (fingerprint)
-- станет:
PRIMARY KEY (project_id, branch, fingerprint)
```

`branch` — git branch на момент события; `first_seen_branch` / `last_seen_branch` остаются как история.

### 2.2. Semantics

- **Negative-merge** — только в своей ветке (уже в ADR-0005 §2.4).
- **`FIXED`** на `main` **не** означает `FIXED` на `release/1.x`. Распространение — **только через git** (merge / cherry-pick): после мержа скан `release/1.x` увидит «не найдено» → `POTENTIALLY_FIXED` → `verify_fix` → `FIXED`.
- **`WONT_FIX`** — на `main` не означает `WONT_FIX` на `release/1.x`. Аналогично.
- **`SUPPRESSED`:**
  - scope `global` — применяется **всем** ветвям;
  - scope `ci` — всем ветвям CI (по умолчанию; `--branch` для точечного);
  - scope `local` — только локально (как сейчас).

### 2.3. Git propagation

| Событие | Как распространяется |
|---|---|
| merge `main → release/1.x` | скан `release/1.x` видит изменения; `FIXED` появляется по факту |
| cherry-pick фикса | аналогично |
| rebase | commit-ordering по ветке; `POTENTIALLY_FIXED` если исчезло |
| merge `release/1.x → main` | аналогично |

**Никакого «автоматического» распространения состояния.** Это соответствует git-семантике: ветки независимы, пока не смержены. Если разработчик хочет «фикс везде» — он мержит/черри-пикает; наша задача — отразить это в состоянии.

### 2.4. Master

- Ключ агрегации: `(project, branch, fp)`.
- `GET /v1/findings?branch=&commit=` — основной способ запроса (ADR-0008 §5); без `branch` — агрегат по всем ветвям (для отчёта), с пометкой per-branch.
- Audit log: события с `branch`.

### 2.5. Координаты событий

- Каждое master-событие сохраняет `branch`/`commit`; snapshot-канал удалён MS-6
  и в per-branch модели не восстанавливается.
- `branch="<unknown>"` — negative-merge запрещён (как в ADR-0006 §2.3).

### 2.6. Migration

- `schema_version` bump → drop + recreate (в духе ADR-0005 §2.7).
- Обратной совместимости нет; breaking change для pre-1.0.0.

---

## 3. Что не меняется

- **`GateEngine`** — работает на materialized status per finding; per-branch — просто ещё одно измерение в PK.
- **`finding_identity`** — `logical_id` (семантический) остаётся кросс-веточным; но записи — per-branch. Одна логическая проблема в разных ветвях — разные записи `shown_findings`.
- **`verify_fix`** — работает в контексте текущей ветки.
- **`scan_project` / `scan_diff` / `scan_file`** — scope per-branch (уже в ADR-0005 §2.4).

---

## 4. Открытые вопросы

| # | Вопрос | Предложение |
|---|---|---|
| 1 | `scope=ci` suppression — все ветви или конфигурируемо? | Все ветви по умолчанию; `--branch` — для точечного |
| 2 | Detached HEAD / tags — как `branch`? | `branch="detached:<sha>"` или `<unknown>`; negative-merge запрещён |
| 3 | `main` vs `master` | Convention, не влияет на модель |
| 4 | Multi-branch UI — как показывать «эта находка на 3 ветвях»? | Не блокер, дизайн-вопрос |
| 5 | Агрегация в отчёте — «уникальных `logical_id` на проекте» vs «сумм per-branch» | Не блокер |

---

## 5. Влияние на другие ADR

| ADR | Что меняется |
|---|---|
| ADR-0005 §2.4 | `branch` в PK; `first_seen_branch`/`last_seen_branch` — история |
| ADR-0006 §3.4 | Правила 1–2 уже про «тот же branch»; PK теперь согласован |
| ADR-0006 §5.5 | Known limitation снимается |
| ADR-0008 §5 | `GET /v1/findings?branch=` становится основным |

---

## 6. План (Фаза 3)

| # | Задача | Зависит |
|---|---|---|
| **PB-1** | Schema bump: PK `(project, branch, fp)` | — |
| **PB-2** | Reconcile: negative-merge per-branch | PB-1 |
| **PB-3** | Master: агрегация per `(project, branch, fp)` | PB-1 |
| **PB-4** | Master API: фильтрация и выдача per branch | PB-3 |
| **PB-5** | Тесты: fix на `main` не закрывает `release/1.x`; merge закрывает | PB-1..4 |
| **PB-6** | Документация: known limitation снята | PB-1..5 |

---

## 7. Не-цели

- Web UI multi-branch view.
- Automatic propagation (это работа git, не наша).
- Cross-branch `FIXED` без merge — не делаем.

---

## 8. Итог

- `PRIMARY KEY (project, branch, fingerprint)`.
- Состояние per-branch; распространение — только через git merge/cherry-pick.
- `global` suppression — cross-branch; `ci` — cross-branch (по умолчанию); `local` — только локально.
- Migration: drop + recreate (pre-1.0.0).
- **Фаза 3**; не блокирует Фазу 2.

---

## 9. Ссылки

- ADR-0001 (fingerprint), ADR-0005 (state machine), ADR-0006 (lifecycle), ADR-0008 (orchestrator modes)
- `storage/stores/shown.py`, `orchestration/reconcile.py`, `appsecgate-master/`, `git.py`

---

## Что это даёт

- **Закрывает «висящее имя»**: ADR-0007 существует, имеет содержание и границы.
- **Фиксирует решение**, даже если реализация отложена: при следующем ревью не будет спора «а что такое per-branch?».
- **Снимает known limitation** формально: в ADR-0006 §5.5 можно сослаться на ADR-0007 как «запланировано».
- **Не блокирует Фазу 2**: реализация — Фаза 3, как договаривались.
