# ADR-0009: Agent implementation model

**Статус:** Proposed (depends on ADR-0008)
**Дата:** 2026-10-31
**Файл:** `docs/adr/ADR-0009-agent-implementation-model.md`
**Контекст:** ADR-0008 вводит два режима оркестрации (agent mode / classic hard-gate). Agent mode требует формализации: что такое агент, какие MCP-тулы он вызывает, как соблюдает policy, что поставляем мы vs пользователь. Без этого agent mode остаётся «на словах».
**Связанные:** ADR-0008 (orchestrator modes), ADR-0006 (gate matrix), ADR-0004 (master), ADR-0005 (state machine), ADR-0007 (per-branch), ADR-0010 (RW-agent, Пауза)

---

## 1. Контекст

- ADR-0008 §2.1: agent mode — default; policy — advisory; write — ro/rw; source — local/master.
- ADR-0008 §4: агенту нужен MCP-тул `check_gate`; детали контракта — здесь (§3).
- ADR-0008 §11 п.2: RW-агент — Пауза; каркас — здесь (§7); детали — ADR-0010.
- Технически всё есть (`scan_project`, `verify_fix`, `suppress_finding`, master API), но **нет контракта «как агент работает»**: порядок вызовов, соблюдение policy, что поставляем мы.
- Владелец (2026-10-31): policy enforcement — **оба** (AGENTS.md + машиночитаемо); RW-агент — **Пауза**.

**Вывод:** нужен ADR, который определяет модель агента, не переопределяя режимы (ADR-0008) и gate-логику (ADR-0006).

---

## 2. Три типа агентов

| Тип | Где живёт | Кто поставляет | Пример |
|---|---|---|---|
| **Dev-agent** | рабочий ноутбук | пользователь (Cline / Claude Code / Cursor) | «проверь и почини» |
| **Server-agent** | сервер рядом с master | **мы** (референс `appsecgate-agent`) | cron, release, agent-loop |
| **CI-agent** | CI-раннер (GitHub Actions) | пользователь (headless dev-agent) | PR-merge, release |

**Dev-agent** — уже работает. Мы поставляем MCP-сервер + AGENTS.md; агент — чужой.

**Server-agent** — референсная Python-обёртка: MCP-клиент + policy + опционально LLM. Поставляем как `appsecgate-agent` (§6).

**CI-agent** — тот же dev-agent в headless-режиме (Claude Code `--print`, Cursor в CI). Мы поставляем пример workflow, не бинарь.

### 2.1. Контракт агента с MCP

Рекомендованная последовательность (не enforced):

```
1. get_config()                    → gates, block_on, policy keys
2. scan_project() | scan_diff()    → findings, counts, requires_confirmation
3. query_findings_db(...)          → контекст, если нужно
4. get_fix_context_batch(fps)      → код вокруг находок
5. [fix code]                      → агент правит (RW, §7 Пауза)
6. verify_fix_batch(fps)           → FIXED / REOPENED / WONT_FIX
7. suppress_finding(...)           → если FP / wont_fix
8. check_gate(scope, policy)       → GateSummary (advisory)
9. [report]                        → markdown/ndjson
```

**Ключевое:** `check_gate` — отдельный MCP-тул (§3), вызывается **после** действий. Не «проверка перед», а «итоговое решение».

---

## 3. MCP-тул `check_gate` — контракт

> ADR-0008 §4 фиксирует необходимость тула; здесь — контракт.

### 3.1. Сигнатура

```python
@mcp.tool()
def check_gate(scope: str = "diff", policy: str = "block") -> GateSummary:
    """Returns GateDecision for current findings under given policy."""
```

- `scope ∈ {file, diff, full}` — соответствует `scan_file` / `scan_diff` / `scan_project`.
- `policy ∈ {warn, block, escalate, fix}` — из ADR-0008 §3.
- Читает `shown_findings` (local) или master (через edge sync).
- Применяет матрицу §2.3 ADR-0006.
- **Не падает.** Агент сам решает, как реагировать.

### 3.2. Ответ

```python
GateSummary:
  should_fail: bool
  by_reason: dict[str, int]          # {reason: count}
  blocked_fps: list[str]
  warned_fps: list[str]
  recommended_action: Literal[
    "proceed",           # можно продолжать
    "verify_fix_batch",  # есть POTENTIALLY_FIXED + critical/high
    "fix_blocked",       # реальные блоки
    "escalate",          # policy=escalate
    "report_only",       # cron/report
  ]
  meta: {
    policy: str,
    scope: str,
    source: str,        # "local" | "master"
    branch: str,
    commit: str,
    generated_at: str,
  }
```

**Reasons** — из ADR-0006 §2.3: `ci_severity`, `unresolved_local`, `reopened`, `unconfirmed_fix`, `unconfirmed_fix_critical`, `suppressed`, `wont_fix`, `wont_fix_other_branch`, `ci_new`.

### 3.3. `recommended_action` — правила

| Условие | `recommended_action` |
|---|---|
| `should_fail == False` и нет `POTENTIALLY_FIXED` с block-on severity | `proceed` |
| `should_fail == False`, но есть `POTENTIALLY_FIXED` с block-on severity | `verify_fix_batch` |
| `should_fail == True`, policy ∈ {block, fix} | `fix_blocked` |
| policy == escalate | `escalate` |
| policy == warn | `report_only` |

`recommended_action` — **машиночитаемая** подсказка. Если агент её игнорирует — это видно в action log (§9).

### 3.4. Обработка ошибок

| Ситуация | Поведение |
|---|---|
| Master недоступен | `source="local"`, warning в `meta`; gate работает на локальном состоянии |
| Нет записей `shown_findings` | `should_fail` по severity-only (`ci_new`); `recommended_action` по policy |
| `scope` невалиден | `ValueError` (Pydantic); агент ловит |

---

## 4. Policy enforcement — оба механизма

### 4.1. AGENTS.md (декларативно)

Шаблон, который поставляем:

```markdown
## AppSecGate policy

Before reporting done:
1. Call `check_gate(scope="diff", policy="block")`.
2. If `summary.should_fail` is true and policy is `block`:
   - Do NOT mark task done.
   - Report blocked findings with reasons.
3. If `summary.recommended_action == "verify_fix_batch"`:
   - Call `verify_fix_batch` on `summary.warned_fps` before reporting.
4. Never suppress without explicit user request.
```

Для dev-agent (Cline, Claude Code), которые читают правила.

### 4.2. `recommended_action` (машиночитаемо)

Для server-agent: runner читает `recommended_action` и действует по policy (§6). Не зависит от LLM-послушания.

### 4.3. Action log (аудит)

Server-agent пишет `action_log.ndjson` — каждый вызов тула, каждый `check_gate`, каждое решение. Если агент не вызвал `check_gate` или не последовал — это видно.

---

## 5. Циклы по архетипам

### 5.1. Dev-agent (solo, shift-left)

```
hook (PostToolUse) → scan_file → [findings] → show → mark_shown
on-demand → scan_project → triage → fix → verify_fix → check_gate(warn) → report
```

**Policy=warn.** Агент показывает, не блокирует. `check_gate` — для отчёта.

### 5.2. Server-agent (agent-wrangler, cron)

```
cron → scan_project(full) → triage → check_gate(escalate) →
  if recommended_action == "fix_blocked": spawn fix-subagent (RW, §7 Пауза)
  else: report to master
```

**Policy=escalate.** `check_gate` возвращает `escalate` → server-agent либо будит человека, либо запускает fix-subagent (RW — §7 Пауза).

### 5.3. CI-agent (classic, PR-merge)

```
pr → scan_diff(base-ref) → check_gate(block) →
  if should_fail: exit 1 (через agent wrapper)
  else: report + exit 0
```

**Policy=block.** Два варианта (ADR-0008 §2.3):
- **(A) CI-agent** (LLM в цепочке): агент вызывает `scan_diff` + `check_gate`, сам решает exit. Недетерминированно.
- **(B) Classic hard-gate** (`appsecgate ci`): детерминированный CLI, без LLM. Воспроизводимо.

**По ADR-0008:** для protected merge / release — **(B)**; для PR с triage-отчётом — **(A)**.

---

## 6. Server-agent — референсная реализация

Отдельный пакет `appsecgate-agent` (изоляция зависимостей, как master):

```
appsecgate-agent/
  __init__.py
  runner.py        # main loop: trigger → scan → check_gate → action
  llm.py           # обёртка над LLM API (OpenAI-compatible / Ollama)
  mcp_client.py    # MCP-клиент (stdio)
  policy.py        # что делать с recommended_action
  triggers.py      # cron, on-demand, agent-loop
  report.py        # markdown/ndjson
  action_log.py    # audit
```

**Runner loop:**

```python
def run(trigger, config):
    mcp = MCPClient(config.mcp_command)
    mcp.initialize()
    log = ActionLog(config.log_path)

    scan = mcp.call("scan_project" if trigger.scope == "full" else "scan_diff")
    log.record("scan", scan)

    gate = mcp.call("check_gate", scope=trigger.scope, policy=trigger.policy)
    log.record("check_gate", gate)

    if trigger.mode == "report":
        return report(gate, scan)

    if gate.recommended_action == "verify_fix_batch":
        # optional: run verify_fix_batch on gate.warned_fps
        ...

    if gate.recommended_action == "fix_blocked" and trigger.policy == "fix":
        # §7 Пауза: RW-агент
        ...

    if trigger.policy == "block" and gate.should_fail:
        exit(1)
    exit(0)
```

**LLM-часть** — только для triage/fix. Для `report` mode LLM **не нужен** — детерминированный Python.

**Когда LLM нужен:**
- `triage` mode — классификация FP/WONT_FIX (опционально);
- `fix` mode — RW, §7 Пауза.

**LLM API:** OpenAI-compatible / Ollama — оба, через конфиг. Для корпоративного — Ollama (локально); для облака — OpenAI-compatible.

---

## 7. RW-agent — Пауза

Каркас, не реализуем сейчас:

```
server-agent → fix-subagent →
  clone → scan → fix → verify_fix → check_gate →
  create branch appsecgate/fix-* → PR → report
```

**Границы (для будущего ADR-0010):**
- только ветки `appsecgate/fix-*`;
- только PR, no force-push;
- бюджет токенов на прогон;
- песочница (отдельный контейнер/runner);
- LLM API — локальный или корпоративный.

**Статус:** Пауза. Модель агента (§2–§6) готова к RW без переделки: `check_gate` возвращает `fix_blocked`, runner может запустить fix-subagent, когда RW появится.

---

## 8. Безопасность

| Риск | Мера |
|---|---|
| Prompt injection через tool results | MCP-тулы возвращают структурированные данные (не свободный текст); AGENTS.md предупреждает |
| Tool poisoning (MCP-сервер подменён) | Пользователь проверяет `tools/list` до первого запроса (статья) |
| Server-agent с LLM читает код проекта | LLM API — локальный (Ollama) или корпоративный (не публичный) |
| RW-агент пушит куда попало | Пауза; границы — ADR-0010 |
| Master API key в server-agent | env / secret store; не в конфиге |
| Агент игнорирует `check_gate` | Action log фиксирует; аудит |

**Инвариант №2** (MCP без сети) не нарушается: server-agent — **вне** MCP-контейнера; MCP-контейнер по-прежнему `network: none`. Server-agent общается с master по сети (edge-роль, как ADR-0004 §4.2).

---

## 9. Наблюдаемость

| Что | Где |
|---|---|
| Вызовы MCP-тулов | action log (server-agent) / MCP-сервер лог |
| `check_gate` вызван? | action log |
| `recommended_action` соблюдён? | action log: сравнение |
| GateSummary | audit на master (`/v1/audit`) |
| Токены / стоимость | action log (если LLM) |

**Action log** — `action_log.ndjson`: каждый вызов тула, каждый `check_gate`, каждое решение. Локальный + опциональный push в `/v1/audit`. Это то, что «докажет эффективность подхода руководству» (статья).

---

## 10. Обработка ошибок

| Ситуация | Поведение |
|---|---|
| MCP-сервер недоступен | server-agent: retry (3), затем fail с `exit 2` |
| Master недоступен | server-agent: `check_gate` работает на local state; warning в report |
| Скан упал (один сканер) | partial result; warning в meta (architecture §6) |
| `check_gate` вернул block, policy=block | `exit 1` |
| `check_gate` вернул escalate | report + (опционально) notify |
| LLM вернул мусор (triage/fix) | fallback: report only |

**Принцип:** server-agent не «падает молча». Либо exit-код, либо report с warning.

---

## 11. Что поставляем мы vs что берёт пользователь

| Компонент | Мы | Пользователь |
|---|---|---|
| MCP-сервер (Docker) | ✅ | — |
| AGENTS.md (правила) | ✅ шаблон | адаптирует |
| MCP-тулы (`scan_*`, `check_gate`, …) | ✅ | — |
| Dev-agent (Cline, Claude Code) | ❌ | ✅ выбирает |
| Server-agent (`appsecgate-agent`) | ✅ референс | запускает |
| CI-agent (headless) | ✅ пример workflow | ✅ запускает |
| Classic hard-gate (`appsecgate ci`) | ✅ (ADR-0008) | ✅ |
| Примеры workflow (agent / cron / release) | ✅ | адаптирует |

**Граница:** мы поставляем MCP-сервер + референсный server-agent + примеры. Пользователь выбирает dev-agent и запускает server-agent/CI.

---

## 12. Последствия

### 12.1. Для ADR-0008

- §4 (`check_gate`) — контракт раскрыт здесь (§3).
- §11 п.2 (RW) — ссылка на §7 здесь / ADR-0010.
- §9 (план) — OR-1/OR-2 = AG-1/AG-2 здесь; не дублировать в `open-tasks.md`, вести как OR-1/OR-2.

### 12.2. Для ADR-0006

- §2.3 gate matrix — без изменений; `check_gate` использует её.
- §5.5 (known limitations) — дополнить: «agent mode policy — advisory; для enforced gate — classic hard-gate (ADR-0008 §2.2)».

### 12.3. Для ADR-0004

- `GET /v1/findings?branch=&commit=` (ADR-0008 §5) — используется server-agent для «актуальной версии».
- `/v1/audit` — принимает action log (опционально).

### 12.4. Для ADR-0005

- Без изменений.

### 12.5. Для ADR-0007

- `check_gate` учитывает `branch` (per-branch state после ADR-0007); сейчас — `last_seen_branch` как fallback.

### 12.6. Файлы для изменения

- `docs/adr/ADR-0008-orchestrator-presets.md` — §4 (ссылка), §11 п.2, §12.
- `docs/adr/ADR-0006-unified-finding-lifecycle-model.md` — §5.5.
- `docs/adr/README.md` — добавить ADR-0009.
- `AGENTS.md` — шаблон policy-правил (§4.1).
- `docs/deploy-agents.md` — примеры workflow.

---

## 13. План внедрения

> **AG-1/AG-2 = OR-1/OR-2 из ADR-0008 §9.** В `open-tasks.md` вести как OR-1/OR-2, не дублировать.

| # | Задача | Зависит | Статус |
|---|---|---|---|
| **AG-3** | AGENTS.md — шаблон с policy-правилами | — | можно сейчас |
| **AG-4** | Пример «agent in CI» (Claude Code headless) | OR-1 | после OR-1 |
| **AG-5** | Server-agent: `report` mode (без LLM) | OR-1, OR-2 | MVP |
| **AG-6** | Server-agent: `triage` mode (LLM) | AG-5 | после MVP |
| **AG-7** | Server-agent: `fix` mode (RW) | §7 Пауза | ADR-0010 |
| **AG-8** | Примеры cron/release workflow | AG-5 | после AG-5 |
| **AG-9** | Action log + audit push | AG-5 | после MVP |

**MVP server-agent** = AG-5 (report) + AG-8 (примеры). Без LLM, детерминированно. Закрывает classic cron/release без RW.

**Блокеры agent mode:** OR-1 (`check_gate`), OR-2 (`branch/commit` в API).

---

## 14. Принятые решения (Q1–Q5)

| # | Вопрос | Решение |
|---|---|---|
| Q1 | `check_gate` — отдельный тул или поле в `scan_*`? | **Отдельный тул** (не раздувать ответы сканов) |
| Q2 | Policy enforcement: AGENTS.md или `recommended_action`? | **Оба** (§4) |
| Q3 | RW-агент | **Пауза** (§7); детали — ADR-0010 |
| Q4 | `branch/commit` в `GET /v1/findings` — обязательны? | **Опциональны**; без них — агрегат по проекту (обратная совместимость) |
| Q5 | Server-agent — отдельный пакет? | **Да** (`appsecgate-agent`), изоляция зависимостей |

---

## 15. Открытые вопросы

1. **Server-agent: LLM API — OpenAI-compatible / Ollama / оба?** Решение: оба, через конфиг.
2. **Action log: локальный файл или master?** Решение: локальный + опциональный push в `/v1/audit`.
3. **`check_gate` для CI-agent: до или после действий?** Тул не навязывает; в AGENTS.md — рекомендация «после». Для CI-agent — допустимо «до» (если policy=block и gate вернул block — не пытаться фиксить).
4. **RW-агент (Пауза):** границы — `appsecgate/fix-*`, PR, no force-push, бюджет. Детали — ADR-0010.

---

## 16. Итог

- **Три типа агентов:** dev (чужой), server (наш референс), CI (headless).
- **Контракт:** `scan_*` → `check_gate` → `recommended_action` → report/exit.
- **Policy:** AGENTS.md (декларативно) + `recommended_action` (машиночитаемо) — оба.
- **`check_gate`** — отдельный MCP-тул; возвращает `GateSummary` с `recommended_action`; не падает.
- **Server-agent MVP:** `report` mode без LLM, детерминированно; LLM — опционально для triage/fix.
- **RW-агент:** Пауза (§7); каркас есть; детали — ADR-0010.
- **Безопасность:** MCP без сети (инвариант №2), server-agent вне контейнера, action log.
- **Что поставляем:** MCP + AGENTS.md + server-agent (референс) + примеры workflow.
- **Блокеры agent mode:** OR-1 (`check_gate`), OR-2 (`branch/commit` в API) — из ADR-0008 §9.

---

## 17. Ссылки

- ADR-0008 (orchestrator modes), ADR-0006 (gate matrix), ADR-0004 (master), ADR-0005 (state machine), ADR-0007 (per-branch), ADR-0010 (RW-agent — Пауза)
- `docs/architecture.md` §3.1, §4.2, §5
- `orchestration/gate.py`, `server/tools/*`, `server/ci.py`, `appsecgate-master/`, `git.py`

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
| ADR-0006 | Unified finding lifecycle model | Accepted (SM-1..3,6; SM-4/5 superseded by MS-6) |
| ADR-0007 | Per-branch state | Proposed (Фаза 3) |
| ADR-0008 | Orchestrator modes | Proposed |
| ADR-0009 | Agent implementation model | Proposed (depends on ADR-0008) |
| ADR-0010 | RW-agent | Proposed (Пауза) |
```
