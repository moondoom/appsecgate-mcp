# ADR-0003: Доставка «показанного локально» в CI для `block_on_unresolved_local`

**Статус:** Paused (superseded in parts by ADR-0006)
**Дата:** 2026-10-30
**Контекст:** Фаза 2, этап 1 — CI-контур и двойные gates
**Решает:** откуда CI узнаёт, какие находки были показаны разработчику локально (killer-фича «ты знал и не починил»)

---

## 1. Контекст

- Product Principle: **Warn-only локально, блокировка только в CI (Фаза 2)**.
  `docs/product-vision.md` §4.3: локально CRITICAL/HIGH → warn, в CI → block;
  «было показано локально и не исправлено» → block (повышенный приоритет).
- `GateEngine` (`orchestration/gate.py`) уже умеет `mode="ci"`,
  `block_on_unresolved_local` и `evaluate_all()` → `GateSummary.should_fail`;
  конфиг `gates.local`/`gates.ci` и дефолты (`mcp-server/config/default.yaml`) есть.
- Источник «показанного» сейчас — один `shown_store` (`shown_findings.db`,
  проектная ось T7, retention 30 дней), который живёт на volume машины
  разработчика (`appsecgate-data`). CI — другая машина/контейнер, доступа
  к этому volume нет.
- Что уже фиксируется локально и должно влиять на CI-gate:
  - **SHOWN** — показанные находки (`shown_findings.db`);
  - **fix_attempts** — `verify_fix`: `fixed` / `not_fixed` / `wont_fix`
    (T12-контракт: читать `verified_status`);
  - **suppressions** со `scope: local | ci | global`
    (`storage/stores/suppression.py`; сейчас фильтрует только local).
- Ограничения, которые нельзя нарушать (AGENTS.md, инварианты):
  - №1 проект монтируется `:ro` — **сервер не пишет в проект**;
  - №2 `network_mode: none` — никаких HTTP-вызовов;
  - №5 `query_findings_db` — только SELECT;
  - нет новых production-зависимостей;
  - `suppress_finding` в Фазе 1 — local и не влияет на CI (двойной контур —
    это фича Фазы 2, а не баг).
- Открытый вопрос `docs/architecture.md` §9.5 «Синхронизация shown_findings
  с master» — вне этого этапа.

## 2. Цели и не-цели

### Цели

| # | Цель | Метрика |
|---|------|---------|
| G1 | CI блокирует по severity (`gates.ci.block_on`) | GateEngine mode=ci |
| G2 | CI блокирует находки, показанные локально и не закрытые | блок `unresolved_local` в CI-прогоне |
| G3 | «Закрытая» = `verify_fix=fixed` ИЛИ suppression со scope `ci`/`global`; scope `local` в CI не снимает блок | таблица решений (§5.2) |
| G4 | Работает офлайн, без master-сервера, без новых зависимостей | этап Фазы 2 без master |
| G5 | Не нарушен ни один инвариант (№1, №2, №5) | code review + тесты |
| G6 | 327+ тестов зелёные | `make check` |

### Не-цели

- Не проектировать master-сервер и сетевую синхронизацию (отдельный этап).
- Не менять сигнатуры существующих MCP-тулов.
- Не добавлять SARIF/CodeQL-интеграцию в этот этап.
- Не менять локальный контур (warn-only) — он зафиксирован Фазой 1.

## 3. Кандидаты

### Вариант А — snapshot в репозитории, обязательный

Агент (имеет rw на проект; сервер — нет, инвариант №1) собирает журнал
показанного в `.appsecgate-mcp/shown.ndjson` и коммитит его. CI читает файл
с `:ro`-маунта. **Нет snapshot → CI-прогон падает с `exit 2`** (fail-closed).

### Вариант Б — только severity-gate на этом этапе

CI блокирует только по `gates.ci.block_on`. `unresolved_local` откладывается
до master-сервера. Killer-фича в первом шаге Фазы 2 отсутствует.

### Вариант В — гибрид: unresolved_local по snapshot, опциональный вход

Как А, но **отсутствие snapshot не ошибка**: CI предупреждает и оценивает
только severity-gate (fail-open для `unresolved_local`, fail-closed для
severity). Легитимное состояние — новый проект без истории показанного.

### Вариант Г — master-сервер сразу

Показанные находки синхронизируются на центральный сервер, CI тянет оттуда.
Требует сеть, сервер, конфликт-резолв (arch §9.5), не поэтапен.

## 4. Сравнительный анализ

| Критерий | А (snapshot, fail-closed) | Б (только severity) | В (snapshot, опц.) | Г (master) |
|---|---|---|---|---|
| Поэтапность (без master) | ✅ | ✅ | ✅ | ❌ |
| Killer-фича работает | ✅ | ❌ | ✅ | ✅ |
| Офлайн / `network none` | ✅ | ✅ | ✅ | ❌ (сеть к master) |
| Новые зависимости/серверы | нет | нет | нет | сервер + сеть |
| Риск пропуска блокировки | мал (snapshot закоммичен) | высокий (фича выключена) | средний (забыли коммитить) | мал |
| Поведение при отсутствии данных | **exit 2** — ложная тревога для нового проекта | не применимо | warning + severity-gate | не применимо |
| Сложность этапа | средняя | низкая | средняя | высокая |

Риск А/В — «ленивый» разработчик может не коммитить snapshot и спрятать от
CI показанные MEDIUM/LOW. Смягчается: severity-gate остаётся всегда;
snapshot накапливается монотонно (перезапись не удаляет ранее показанные fp);
CI выводит заметный warning при отсутствии snapshot.

## 5. Решение

**Выбран вариант В.** При решении владельца легко ужесточается до А
(флаг `--require-shown-snapshot`).

### 5.1. Контракт CLI (этап CI-2)

```
appsecgate ci --project PATH [--base-ref origin/main]
              [--shown-snapshot .appsecgate-mcp/shown.ndjson]
              [--format text|ndjson]
```

- diff против `--base-ref` (`git diff <ref>...HEAD`) — новая функция `git.py`;
- скан через существующий `ScanCoordinator.scan(mode="diff", persist=False)`
  — в CI ничего не пишется в shown;
- оценка `GateEngine.evaluate_all(findings, mode="ci")`;
- **exit codes: `0` = pass, `1` = blocked, `2` = ошибка инфраструктуры**
  (git/сканеры/конфиг) — отличаем «находки» от «CI сломан».

### 5.2. Таблица решений GateEngine в CI

| Находка | `verified_status` | suppression scope | Действие |
|---|---|---|---|
| severity ∈ `block_on` | — | — | **block** (`ci_severity`) |
| fp ∈ shown (snapshot) | null / `not_fixed` | — | **block** (`unresolved_local`) |
| fp ∈ shown | `fixed` | — | не блокирует |
| fp ∈ shown | `wont_fix` | — | **block** (`wont_fix`) |
| fp ∈ shown | — | `ci` / `global` | не блокирует |
| fp ∈ shown | — | `local` | **block** (`unresolved_local`) — двойной контур |
| fp ∉ shown | — | — | warn/info по `gates.ci` |

### 5.3. Источник «показанного» в GateEngine

Абстракция «shown-source»: локальный `shown_store` (тесты/локальный режим,
интерфейс `was_shown`) **или** snapshot-источник (CI, интерфейс `record`).
`GateEngine._evaluate_ci` поддерживает оба интерфейса без изменения
публичного контракта `GateEngine`.

## 6. Формат snapshot

### 6.1. Файл

`.appsecgate-mcp/shown.ndjson`, одна находка на строку, **redacted**
(инвариант №4 — данные берутся из публичных views, сырых секретов там нет):

```json
{"fp":"0691d13f93462eba","rule_id":"gitleaks.github-pat","file":"src/main.py",
 "line":42,"severity":"high","shown_at":"2026-10-30T12:00:00Z",
 "verified_status":null,"suppression_scope":null}
```

### 6.2. Кто пишет

**Агент**, не сервер (инвариант №1): агент собирает данные через
`query_findings_db` (SELECT `v_findings`) + `get_scan_history`
(`fix_attempts`, suppressions) и сохраняет файл в проекте. Серверных прав
на запись в проект не требуется и не добавляется.

### 6.3. Монотонность

Snapshot — «множество показанных fp»: при обновлении ранее показанные записи
не удаляются (иначе откат страницы показа «спрячет» находку). Обновление —
перезапись файла полным множеством. Merge-конфликты возможны, но строки
независимы; резолв — union строк.

### 6.4. Устаревание

Поле `shown_at` + retention 30 дней (как в `shown_findings`). Просроченные
записи CI игнорирует с warning.

## 7. Принятые решения (Q1–Q5)

| # | Вопрос | Решение |
|---|---|---|
| Q1 | Механизм доставки показанного | **В** — snapshot в репозитории, опциональный вход |
| Q2 | Поведение при отсутствии snapshot | warning + severity-gate; флаг `--require-shown-snapshot` ужесточает до fail-closed |
| Q3 | Новое поле конфига `gates.ci.diff_base_ref` (default `origin/main`) | разрешено |
| Q4 | Кто пишет snapshot | агент (инвариант №1) |
| Q5 | Расширять ли содержимое `export_snapshot` полями `verified_status`/`suppression_scope` | да, без смены сигнатуры тула |

## 8. План внедрения

| Этап | Содержание | Репо |
|---|---|---|
| **CI-1** | Принятие ADR-0003 (этот документ), обновление `docs/adr/README.md`, `docs/architecture.md` §8 | docs |
| **CI-2** | CLI `appsecgate ci`: base-ref diff (`git.py`), exit codes 0/1/2, `--format text\|ndjson` | mcp-server |
| **CI-3** | shown-source абстракция: snapshot-парсер + подключение к `GateEngine` | mcp-server |
| **CI-4** | Suppression/verify_fix в CI по таблице §5.2 (snapshot-поля) | mcp-server |
| **CI-5** | Конфиг `gates.ci.diff_base_ref` + env override | mcp-server |
| **CI-6** | Пример `.github/workflows/appsecgate-ci.yml` + README + `deploy-agents.md` | docs |
| **CI-7** | Тесты: `test_gate` (snapshot-source, scope), `test_ci_cli` (exit 0/1/2, base-ref, ndjson); `make check` зелёный | mcp-server |

## 9. Тестирование

- Unit: `GateEngine` с snapshot-source — каждый ряд таблицы §5.2; CLI `ci` —
  exit 0/1/2, пустой diff, отсутствующий snapshot, `--base-ref` без `origin/main`.
- Регресс: 327 тестов (`make check`), инварианты №1/№2 (CI-контейнер тоже
  `:ro` + `network none`).
- E2E (отдельный этап, по мотивам T14): полигон + фиктивный PR-дифф →
  блокировка/пропуск.

## 10. Ссылки

- `docs/architecture.md` §8 (границы Фазы 1/2), §9.5 (синхронизация — вне этапа)
- `docs/product-vision.md` §4.2–4.3 (воронка эскалации, двойной контур)
- `orchestration/gate.py`, `config/models.py`, `storage/stores/suppression.py`,
  `server/cli.py`, `git.py`
- `docs/adr/ADR-0001-fingerprint-and-semantic-dedup.md` — формат ADR, фундамент fingerprint
