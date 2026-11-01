# ADR-0010: RW-agent (read-write агент) — Пауза

**Статус:** Proposed (Пауза)
**Дата:** 2026-11-01
**Файл:** `docs/adr/ADR-0010-rw-agent.md`
**Контекст:** ADR-0009 §7 фиксирует каркас RW-agent (fix-subagent, который пишет код и открывает PR) и выносит детали в отдельный ADR. Этот ADR закрывает висячую ссылку и фиксирует границы, в которых RW-agent будет реализован, когда выйдет из Паузы. Реализация **не** входит в текущий этап.
**Связанные:** ADR-0009 (agent model), ADR-0008 (orchestrator modes), ADR-0006 (gate matrix), ADR-0004 (master), ADR-0002 (language consistency & agent fix reliability)

---

## 1. Контекст

### 1.1. Что уже работает

- **Dev-agent (RO)** — ADR-0009 §2: чужой агент (Cline / Claude Code / Cursor) правит код сам, MCP-сервер только сканирует, триажит, верифицирует.
- **Server-agent (RO)** — ADR-0009 §6: референсный `appsecgate-agent` в режиме `report` / `triage`; `check_gate` возвращает `fix_blocked`, но сам агент **не правит** код (только сообщает).
- **`verify_fix_batch`** — уже есть, проверяет, закрылась ли находка после правки (не важно, кем правка сделана).
- **`check_gate`** — ADR-0009 §3: возвращает `recommended_action ∈ {proceed, verify_fix_batch, fix_blocked, escalate, report_only}`.

### 1.2. Чего нет

RW-agent — это агент, который **сам** применяет фикс (`fix_blocked` → правит код → `verify_fix_batch` → PR). Сейчас `recommended_action=fix_blocked` — терминальное состояние: server-agent отчитывается и останавливается. Никто не пишет код за человека.

### 1.3. Почему Пауза

- **Безопасность.** Агент с правом записи в репозиторий — качественно другой уровень риска: prompt injection в tool results, галлюцинации в патче, «оптимизация» не того файла, утечка через PR-описание.
- **Зрелость.** Без стабильного `check_gate`, без детерминированной верификации (ADR-0002), без песочницы — RW-агент опаснее, чем полезнее.
- **Приоритет.** Фаза 1 и 2 (MS-*, CI-*) ещё не закрыты. RW — Фаза 3+.
- **Экономика.** RW-агент дорог по токенам (fix + verify + retry loop); без бюджета и метрик — неконтролируемый расход.

**Решение:** каркас зафиксирован (этот ADR), реализация — **Пауза**. Un-pause — явным решением владельца, с обновлением этого ADR (статус → Proposed, затем Accepted) и планом RW-1…RW-N.

---

## 2. Решение

### 2.1. Что такое RW-agent

**RW-agent** — это **fix-subagent** server-agent'а, запускаемый только при `recommended_action == "fix_blocked"` и `policy ∈ {fix, escalate}`. Он:

1. Работает в **изолированной копии репозитория** (клонированной с master/branch), не в рабочей директории пользователя.
2. Применяет правки **только** в ветке `appsecgate/fix-<scan_run_id>-<n>`.
3. Открывает **PR** (draft) с описанием: какие находки, какие fingerprint, какой `check_gate` до/после, какие файлы затронуты.
4. **Не мержит**, не пушит в `main`/`release/*`, не делает force-push, не трогает защищённые ветки.
5. Проходит `verify_fix_batch` и повторный `check_gate` перед открытием PR; если фикс не подтверждён — PR не открывается, отчёт в master с `fix_attempt_status=failed`.

### 2.2. Границы (жёсткие, не конфигурируются в сторону ослабления)

| Граница | Значение |
|---------|----------|
| **Ветки для записи** | Только `appsecgate/fix-*`; префикс `appsecgate/` — зарезервирован |
| **Действия с git** | `clone`, `checkout -b`, `commit`, `push` (только в `appsecgate/fix-*`), открыть PR (draft) |
| **Запрещено** | Force-push, push в `main`/`master`/`release/*`, merge, tag, `git filter-branch`, изменение `.git/config`, submodules, LFS-pointer подмена |
| **Файлы** | Только те, где `check_gate` указал `blocked_fps`; правки вне этого набора — откат, отчёт |
| **Секреты** | Не читает `.env`, `*.pem`, `*.key`, `secrets/*`; если находка в таком файле — `suppress`/`escalate`, не фикс |
| **Сеть** | Только LLM API (локальный/корпоративный) и master (edge-роль); без произвольного egress |
| **Песочница** | Отдельный контейнер/runner, `:ro`-монтирование исходников, `rw` — только копия; без `docker.sock`; `no-new-privileges`; `cap_drop: ALL` |
| **Бюджет** | Лимит токенов на прогон (env `APPSECGATE_RW_TOKEN_BUDGET`, default — 200k); при исчерпании — стоп, отчёт, не «дожимать» |
| **LLM API** | Только локальный (Ollama) или корпоративный (OpenAI-compatible с закрытым egress); публичный API — запрещён |
| **Prompt injection** | MCP-тулы возвращают структурированные данные (не свободный текст); tool results не интерпретируются как инструкции; отдельный «input sanitizer» на стороне RW-agent |

### 2.3. Цикл

```
server-agent (policy=fix, recommended_action=fix_blocked)
  → spawn fix-subagent (RW) в песочнице
      1. clone репозитория (branch из scan_completed)
      2. checkout -b appsecgate/fix-<scan_run_id>-<n>
      3. для каждого blocked_fp:
           get_fix_context_batch([fp]) → патч (LLM)
           apply → verify_fix_batch([fp])
           если not_fixed: retry (≤ K=2), иначе — пропустить, отчёт
      4. повторный scan_diff + check_gate(scope="diff", policy="fix")
      5. если should_fail=False и нет новых блокирующих:
           commit, push, open draft PR
         иначе: отчёт failed, PR не открывается
      6. отчёт в master (/v1/events: fix_attempt_*)
  → server-agent читает отчёт, решает: notify / escalate / done
```

### 2.4. События (расширение ADR-0004 §5.1; формат — после un-pause)

- `fix_attempt_started` — `scan_run_id`, `branch`, `fps[]`, `model`, `budget`.
- `fix_attempt_completed` — `fix_attempt_id`, `status ∈ {fixed|partial|failed}`, `pr_url` (если открыт), `fps_fixed[]`, `fps_remaining[]`, `tokens_used`, `duration`.
- `fix_attempt_aborted` — причина (`budget_exhausted`, `sandbox_violation`, `prompt_injection_suspected`, `gate_still_blocked`).

Схема и API (`GET /v1/fix-attempts?scan_run_id=`) — детализируются при un-pause, чтобы не плодить спекулятивные контракты. Пока фиксируем только **типы** и **инвариант**: события immutable, идемпотентны, redaction.

### 2.5. Связь с `check_gate` (ADR-0009 §3)

`check_gate` **не меняется**. RW-agent — потребитель `recommended_action=fix_blocked`, а не новая ветка в gate. После фикса — повторный `check_gate`, чтобы подтвердить, что блокировка снята (это и есть критерий «фикс сработал» на уровне CI-семантики).

### 2.6. Связь с `verify_fix_batch`

`verify_fix_batch` уже есть и не меняется. RW-agent вызывает его после каждой правки; `FIXED` — обязательное условие для PR. `REOPENED`/`not_fixed` — retry (≤ K), затем `partial`/`failed`.

---

## 3. Почему Пауза (обоснование)

| Причина | Что нужно до un-pause |
|---------|------------------------|
| **Незрелость gate** | `check_gate` (OR-1) и `branch/commit` в API (OR-2) — блокеры agent mode (ADR-0009 §13); без них `fix_blocked` недетерминирован |
| **Незрелость верификации** | ADR-0002 (language consistency, agent fix reliability) — Proposed; без него `verify_fix` может ложно подтверждать фикс |
| **Безопасность** | Песочница, input sanitizer, egress-контроль, secret-фильтры — не реализованы |
| **Экономика** | Нет бюджета токенов и метрик `fix_attempt_*`; без них RW-агент неконтролируем |
| **Приоритет** | Фаза 1 (MCP) и Фаза 2 (master, CI, ADR-0004/0006/0007) не закрыты; RW — Фаза 3+ |
| **Юридическое** | MIT-код + AGPL/Commons Clause сканеры (architecture §8.1) — RW-агент применяет фиксы, лицензионная чистота патчей требует проверки (не блокер ADR, но условие un-pause) |

**Un-pause-триггер:** ADR-0002 Accepted + OR-1/OR-2 закрыты + песочница и input sanitizer реализованы + бюджет/метрики `fix_attempt_*` в master. Только тогда статус → Proposed, затем Accepted, с планом RW-1…RW-N.

---

## 4. Что не входит (не-цели)

- Автоматический merge PR. Никогда — только человек (или отдельный approve-flow, вне этого ADR).
- Автоматическое закрытие находок без PR (только через `suppress_finding` по явному запросу — это RO-путь, не RW).
- RW для CI-agent (PR-merge pipeline) — только server-agent, не CI. CI остаётся read-only.
- Multi-repo orchestration (один fix-subagent = один репозиторий = один PR).
- Автономная работа без `recommended_action=fix_blocked` — RW-agent не запускается «по своему желанию».
- Замена dev-agent: dev-agent правит код сам, RW — для server/cron сценариев.

---

## 5. План (когда un-pause)

Скелет, детализируется при активации:

| # | Задача | Зависит |
|---|--------|---------|
| **RW-1** | Песочница fix-subagent (контейнер, `:ro` источник, `rw` копия, egress-control) | un-pause |
| **RW-2** | Input sanitizer + secret-фильтр (не читает `.env`, `*.pem`, `secrets/*`) | RW-1 |
| **RW-3** | `fix-subagent` loop: clone → checkout `appsecgate/fix-*` → apply → verify → retry(≤K) → gate | RW-1, RW-2 |
| **RW-4** | PR creation (draft), шаблон описания (findings, fp, gate before/after, files) | RW-3 |
| **RW-5** | Бюджет токенов + метрики `fix_attempt_*`; события в master | RW-3 |
| **RW-6** | Интеграция в server-agent: `fix_blocked` + `policy=fix` → spawn | RW-3, RW-5 |
| **RW-7** | Тесты: unit (границы git), интеграция (sandbox escape attempts), E2E (fix → PR → verify) | RW-1…RW-6 |
| **RW-8** | Документация: `docs/deploy-rw-agent.md`, границы, отказ от ответственности | RW-7 |

**MVP (если un-pause)** = RW-1…RW-6 + RW-7 (базовые тесты). RW-8 — до релиза.

---

## 6. Безопасность (сводно)

| Риск | Мера |
|------|------|
| Prompt injection через tool results | Структурированные данные, не свободный текст; input sanitizer; LLM не видит «инструкций» от сканеров |
| Галлюцинация в патче | `verify_fix_batch` обязателен; `check_gate` после фикса; retry ≤ K; иначе `failed`, PR не открывается |
| Утечка через PR-описание | Redaction на приёме (инвариант №4); шаблон PR без кода/секретов, только `file:line`, fp, gate |
| Push в защищённую ветку | Жёсткая граница: только `appsecgate/fix-*`; pre-push hook + проверка на стороне master |
| Force-push / history rewrite | Запрещено на уровне sandbox git config; проверка в RW-agent loop |
| Sandbox escape | `:ro` источник, `rw` копия, `no-new-privileges`, `cap_drop: ALL`, без `docker.sock` |
| Публичный LLM API | Запрещён; только локальный/корпоративный |
| Токен-бюджет | Env-лимит, стоп при исчерпании, отчёт |
| «Уговорить» агента игнорировать границы | Границы реализованы в коде runner, не в промпте; LLM не решает «можно ли force-push» — это проверка в коде |

**Инварианты:**
- **№1** (`:ro` проекта) — источник клонируется; правки в копии, не в проекте.
- **№2** (MCP без сети) — не нарушается: fix-subagent — **вне** MCP-контейнера, как server-agent (ADR-0009 §8).
- **№4** (redaction) — PR-описание и события проходят redaction.

---

## 7. Что меняется в других ADR

| ADR | Что меняется |
|-----|--------------|
| **ADR-0009 §7** | Заменяется ссылкой на этот ADR: «детали — ADR-0010 (Пауза)»; каркас §7 остаётся как high-level, не дублируется |
| **ADR-0009 §15 п.4** | Ссылка на ADR-0010; вопрос «границы» — закрыт здесь (§2.2) |
| **ADR-0009 §17** | Ссылка «ADR-0010 (RW-agent — Пауза)» — теперь файл существует |
| **ADR-0009 §18** | Строка README `ADR-0010 | RW-agent | Proposed (Пауза)` — файл есть |
| **ADR-0004** | Новые типы событий (`fix_attempt_*`) — добавить при un-pause, не сейчас |
| **ADR-0008** | Режимы оркестрации не меняются; `policy=fix` — уже есть |
| **ADR-0006** | Gate matrix не меняется |

---

## 8. Открытые вопросы (для un-pause)

| # | Вопрос | Предложение |
|---|--------|-------------|
| 1 | K (retry) для fix-subagent | 2 по умолчанию; конфигурируется |
| 2 | Бюджет токенов на прогон | 200k default; env |
| 3 | Один PR на `scan_run_id` или на `blocked_fp` | Один на `scan_run_id` (все `blocked_fps` в одном PR), если файлы не конфликтуют; иначе — несколько |
| 4 | Что если `check_gate` после фикса всё ещё `blocked` | Отчёт `partial`; PR не открывается; эскалация человеку |
| 5 | Секреты: `suppress` или `escalate` при находке в `.env`/`*.pem` | `escalate` (не suppress): это сигнал, а не FP; фикс не автоматизируется |
| 6 | Multi-branch (ADR-0007) | RW работает в одной ветке (из `scan_completed.branch`); multi-branch — отдельный этап |
| 7 | Юридическая чистота патчей (AGPL/Commons Clause сканеры) | Проверить при un-pause; если правило AGPL — фикс не применяется, `escalate` |
| 8 | Формат `fix_attempt_*` событий и `GET /v1/fix-attempts` | Детализировать при un-pause (не плодить спекулятивные контракты) |

---

## 9. Итог

- **RW-agent = fix-subagent**, запускаемый только при `recommended_action=fix_blocked` и `policy ∈ {fix, escalate}`.
- **Границы жёсткие**: только `appsecgate/fix-*`, только PR (draft), no force-push, no merge, sandbox, secret-фильтр, бюджет токенов, локальный/корпоративный LLM.
- **`check_gate` и `verify_fix_batch` не меняются** — RW-agent их потребитель.
- **Статус: Пауза.** Un-pause — при ADR-0002 Accepted + OR-1/OR-2 закрыты + песочница/sanitizer/бюджет/метрики готовы.
- **Не-цели**: авто-merge, RW для CI, multi-repo, автономная работа без `fix_blocked`.
- **Закрывает висячую ссылку** ADR-0009 §7/§15/§17/§18 — файл существует, статус согласован.

---

## 10. Ссылки

- ADR-0009 (agent model) §2, §3 (`check_gate`), §6 (server-agent), §7 (каркас RW), §8 (безопасность), §15 п.4
- ADR-0008 (orchestrator modes) — `policy=fix`
- ADR-0006 (gate matrix) — `fix_blocked`
- ADR-0002 (language consistency & agent fix reliability) — блокер un-pause
- ADR-0004 (master) — события `fix_attempt_*` (при un-pause)
- `orchestration/gate.py`, `server/tools/*`, `appsecgate-agent/`, `git.py`