# ADR-0008: Orchestrator modes — agent mode и classic hard-gate

**Статус:** Proposed
**Дата:** 2026-10-31
**Файл:** `docs/adr/ADR-0008-orchestrator-presets.md`
**Контекст:** Фаза 2 закрыта технически (ADR-0004 MS-1..7), но архитектурно дрейфует: CI был задуман как агент (статья, fig. 2–3), а реализован как отдельный CLI (ADR-0003). Snapshot удалён MS-6. Требуется формализовать, как запускается проверка и кто принимает решение.
**Связанные:** ADR-0003 (CI CLI — переосмысляется), ADR-0004 (master), ADR-0005 (state machine), ADR-0006 (gate matrix), ADR-0007 (per-branch, Фаза 3), ADR-0009 (agent implementation model)

---

## 1. Контекст

- В статье и в формулировках владельца CI — это **агент, запущенный на сервере**: он сканирует, читает master, применяет политику, при RW — фиксит.
- В ADR-0003 CI был смоделирован как **отдельный CLI** с exit-кодами. Это решило проблему «как упасть в пайплайне», но породило drift: snapshot-костыль, отдельный контур, «офлайн-CI».
- Master (ADR-0004) сделал snapshot ненужным; MS-6 удалил его. `appsecgate ci` остался осиротевшим: логика в нём — та же, что в MCP-тулах, но интерфейс другой.
- Владелец (2026-10-31): **режим CI оставить для classic, где нужен твёрдый гейт.** То есть CLI — не drift целиком, а валидный режим для одного архетипа.

**Вывод:** два режима оркестрации сосуществуют; их надо различить и зафиксировать, а не выбирать один.

---

## 2. Решение

Два режима над одним субстратом (MCP-тулы + `GateEngine` + master + state machine ADR-0006).

### 2.1. Agent mode (default)

- Агент (Claude Code / Cursor / server-side agent) вызывает MCP-тулы: `scan_project`, `query_findings_db`, `verify_fix_batch`, `suppress_finding`, `get_fix_context`, `check_gate`.
- **Policy — advisory.** Агент читает `GateDecision` (через MCP-тул `check_gate`, §4) и должен следовать; но LLM может отклониться.
- **Write — ro/rw.** RW только в agent mode: агент правит код, делает PR.
- **Source — local/master.** Local на dev, master на сервере.
- Для: solo (dev, shift-left), agent-wrangler (много агентов, escalate/fix).

### 2.2. Classic hard-gate mode (CLI)

- `appsecgate ci` — детерминированный запуск `GateEngine` без LLM в цепочке решения.
- **Policy — enforced.** Exit-коды `0/1/2`; воспроизводимо.
- **Write — только ro.** CLI не правит код.
- **Source — master** (после MS-6; local для dev-CLI, опционально).
- Для: classic, где нужен аудируемый/reproducible gate: PR-merge, release-build.

### 2.3. Почему оба

| Критерий | Agent mode | Classic hard-gate |
|---|---|---|
| Воспроизводимость | зависит от LLM | детерминированная |
| Адаптивность (fix, triage) | ✅ | ❌ |
| Аудит | через action log | exit-код + отчёт |
| Стоимость | токены | ~0 |
| Пригоден для protected merge / release | 🟡 (LLM variance) | ✅ |
| Пригоден для «пойди и почини» | ✅ | ❌ |

**Правило:** если результат должен быть **воспроизводим и аудируем** (release, protected merge) — hard-gate. Если нужна **адаптивность** (fix, triage, отчёт) — agent mode.

---

## 3. Оси оркестратора

`Orchestrator = mode × trigger × scope × policy × write × shown-source`

| Ось | Значения | Комментарий |
|---|---|---|
| `mode` | `agent` \| `cli` | §2 |
| `trigger` | `hook` \| `pre-commit` \| `pre-push` \| `pr` \| `merge` \| `release` \| `cron` \| `agent-loop` \| `on-demand` | |
| `scope` | `file` \| `diff` \| `full` | соответствует `scan_file` / `scan_diff` / `scan_project` |
| `policy` | `warn` \| `block` \| `escalate` \| `fix` | в cli — enforced; в agent — advisory |
| `write` | `ro` \| `rw` | rw только в agent mode |
| `shown-source` | `local` \| `master` | snapshot удалён MS-6 |

---

## 4. MCP-тул `check_gate` (для agent mode)

В agent mode агенту нужен способ получить решение gate, не дублируя логику:

```python
@mcp.tool()
def check_gate(scope: str = "diff", policy: str = "block") -> GateSummary:
    """Returns GateDecision for current findings under given policy."""
```

- Читает `shown_findings` (local) или master (через edge sync).
- Применяет матрицу §2.3 ADR-0006.
- **Не падает.** Агент сам решает, как реагировать.

**Детали контракта** (`GateSummary`, `recommended_action`, обработка ошибок) — **ADR-0009 §3**. Здесь фиксируется только необходимость тула; реализация — в ADR-0009.

---

## 5. API master: «актуальная версия»

Для agent-wrangler (`GET /v1/findings` сейчас без branch/commit):

```
GET /v1/findings?project=&branch=&commit=&state=
```

- `branch` / `commit` — опциональные; без них — агрегат по проекту.
- С ними — состояние на конкретный `(branch, commit)`, с fallback на `last_seen_commit` (если точного нет).
- Ответ — `{fp, status, severity, first_seen_branch, last_seen_branch, suppression_scope}`.

Это и есть ответ на «какая сейчас актуальная версия» — явный контракт, а не «догадайся по событиям».

---

## 6. Пресеты по архетипам

| Архетип | Mode | Trigger | Scope | Policy | Write | Source |
|---|---|---|---|---|---|---|
| **Solo** (dev) | agent | hook / on-demand | file/diff | warn | ro | local |
| **Solo** (pre-push) | cli | pre-push | diff | warn (opt block) | ro | local |
| **Agent-wrangler** | agent | agent-loop / on-demand | diff/full | escalate | ro | master |
| **Agent-wrangler** (fix) | agent | agent-loop | file | fix | **rw** | master |
| **Classic** (PR) | cli | pr | diff | block | ro | master |
| **Classic** (merge) | cli | merge | diff/full | block | ro | master |
| **Classic** (cron) | cli | cron | full | escalate (report) | ro | master |
| **Classic** (release) | cli | release | full | block | ro | master |

**Замечания:**
- Classic использует **оба режима**: agent для triage/отчёта (cron), cli для gate (PR/release).
- Solo использует оба: agent для shift-left, cli для pre-push (опционально).
- Agent-wrangler — только agent mode; cli там не нужен (нет воспроизводимого gate-сценария).

---

## 7. Судьба legacy `appsecgate ci`

- **Не удалять.** Это classic hard-gate mode.
- **Заморозить scope:** новые фичи — только если нужны classic (branch/commit, `--format`, `by_reason`).
- **Переименовать в доках:** «classic hard-gate runner», не «the CI».
- **`--shown-source`:** `master` (default) | `local` (dev-CLI). `snapshot` — удалён, не воскрешать.
- **`.github/workflows/appsecgate-ci.yml`** — остаётся как пример **classic hard-gate**, не «универсальный CI».
- **Не развивать** в сторону agent mode (для этого есть MCP-тулы).

---

## 8. Последствия

### 8.1. Для ADR-0003

- Статус: **`Repurposed as classic hard-gate mode`** (не «Paused»).
- §5.1 (CLI) — остаётся, `--shown-source {master,local}`.
- §5.2 (gate table) — заменена ADR-0006 §2.3 (уже).
- §5.3/§6 (snapshot) — помечены «удалено MS-6, историческое».

### 8.2. Для ADR-0006

- Gate matrix §2.3 — общая для обоих режимов.
- В agent mode policy — advisory; в cli — enforced. Добавить в §2.3 сноску.
- §5.5 (known limitations) — дополнить: «agent mode policy — advisory; для enforced gate — classic hard-gate (ADR-0008 §2.2)».

### 8.3. Для ADR-0004

- `GET /v1/findings` — расширяется `branch`/`commit` (§5).
- Всё остальное без изменений.

### 8.4. Для ADR-0005

- Без изменений.

### 8.5. Для ADR-0009

- ADR-0009 раскрывает agent mode (три типа агентов, `check_gate` контракт, server-agent, RW-агент — Пауза). ADR-0008 — только режимы и границы.

### 8.6. Файлы для изменения

- `docs/adr/ADR-0003-ci-unresolved-local-delivery.md` — статус, пометки snapshot.
- `docs/adr/ADR-0006-unified-finding-lifecycle-model.md` — §5.5, §2.3 сноска.
- `docs/adr/README.md` — статусы ADR-0003/0008/0009.
- `docs/deploy-agents.md` — «два режима», когда какой.
- `server/ci.py` — переименование в доках (код не трогаем).

---

## 9. План внедрения

| # | Задача | Зависит |
|---|---|---|
| **OR-1** | MCP-тул `check_gate` (§4) — контракт в ADR-0009 §3 | ADR-0006 SM-2 (есть) |
| **OR-2** | `GET /v1/findings?branch=&commit=` (§5) | ADR-0004 MS-4 (есть) |
| **OR-3** | ADR-0003: статус «Repurposed as classic hard-gate»; §5.3/§6 — «историческое» | — |
| **OR-4** | ADR-0006: сноска advisory/enforced; §5.5 дополнить | — |
| **OR-5** | Документация: «два режима», когда какой | OR-1..4 |
| **OR-6** | Примеры workflow: classic hard-gate (PR/release/cron) | — |
| **OR-7** | Пример «agent in CI» (headless dev-agent) | OR-1, ADR-0009 |

OR-1 и OR-2 — блокеры agent mode. OR-3..4 — документация. OR-6..7 — примеры.

**AG-1/AG-2** (из ADR-0009) = OR-1/OR-2 — это одни и те же задачи, просто в разных ADR. Вести в `open-tasks.md` как OR-1/OR-2, чтобы не дублировать.

---

## 10. Не-цели

- Web UI, RBAC, ASOC/DefectDojo — вне scope.
- Multi-version (per-branch) — ADR-0007, Фаза 3.
- Удаление `appsecgate ci` — нет, это classic hard-gate.
- Воскрешение snapshot — нет.
- Детали реализации агента (три типа, server-agent, action log) — ADR-0009.
- Формализация agent-to-agent (промпт-инъекции, переговоры) — вне scope.

---

## 11. Открытые вопросы

1. **`check_gate` — отдельный тул или поле в `scan_*`?** Отдельный тул (не раздувать ответы сканов). Контракт — ADR-0009 §3.
2. **RW-агент** — Пауза; каркас в ADR-0009 §7, детали — ADR-0010.
3. **`branch/commit` в `GET /v1/findings` — обязательны?** Опциональны; без них — агрегат по проекту (обратная совместимость).
4. **Classic cron: report или block?** `escalate (report)` — по умолчанию; `block` — для release. Пресет §6.

---

## 12. Итог

- **Два режима, один субстрат.** Agent mode — default (solo, agent-wrangler). Classic hard-gate — CLI (classic PR/release).
- **`appsecgate ci` не drift, а classic hard-gate.** Заморозить, не развивать, переименовать в доках.
- **Snapshot не воскрешать.** Master — источник истины.
- **Agent mode требует двух добавок:** MCP-тул `check_gate` + `branch/commit` в `GET /v1/findings`.
- **Classic использует оба режима:** agent для triage/cron, cli для gate.
- **Детали agent mode** — ADR-0009; RW-агент — Пауза (ADR-0010).

---

## 13. Ссылки

- ADR-0003 (CI-контур — переосмысляется), ADR-0004 (master), ADR-0005 (state machine), ADR-0006 (gate matrix), ADR-0007 (per-branch), ADR-0009 (agent implementation model)
- `docs/architecture.md` §3.1, §4.1–4.2, §8
- `orchestration/gate.py`, `server/ci.py`, `server/tools/*`, `appsecgate-master/`, `git.py`

---

## 14. Изменения в `docs/adr/README.md`

```markdown
| ADR | Название | Статус |
|---|---|---|
| ADR-0001 | Fingerprint and semantic dedup | Accepted |
| ADR-0002 | Language consistency & agent fix reliability | Proposed |
| ADR-0003 | CI unresolved local delivery | Repurposed as classic hard-gate (ADR-0008) |
| ADR-0004 | Master server sync | Accepted (MS-1..7; MS-8 ⏸) |
| ADR-0005 | Project reconciliation & shown state machine | Accepted |
| ADR-0006 | Unified finding lifecycle model | Accepted (SM-1..3,6; SM-4/5 superseded by MS-6) |
| ADR-0007 | Per-branch state | Proposed (Фаза 3) |
| ADR-0008 | Orchestrator modes | Proposed |
| ADR-0009 | Agent implementation model | Proposed (depends on ADR-0008) |
```