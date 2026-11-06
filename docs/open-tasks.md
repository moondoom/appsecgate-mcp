# Открытые задачи

> Активные пункты на 2026-11-01. Закрытые задачи — `docs/history/phase-1-2-completed.md`,
> детали реализации — `docs/history/implementation-notes.md`.
> Дизайн-решения — `docs/adr/`.

## Фактическое состояние

- Фаза 1 и технические этапы CI-1…CI-7, MS-1…MS-7 завершены.
- В scanner MCP зарегистрировано 17 тулов; `check_gate` реализован (OR-1).
- `GET /v1/findings` поддерживает фильтры `state`, `branch` и `commit` (OR-2).
- `appsecgate-agent` реализует только детерминированный report MVP без LLM.
- Master поддерживает SQLite WAL (default) и PostgreSQL 16 с RLS/API-key auth;
  read-only MCP-master реализован (ADR-0013/0015), `scan_run` не реализован.
- `appsecgate-mcp agent --mode=ro` — autonomous triage с полным inventory,
  controller loop/restart/compaction и master knowledge (ADR-0015).
- ADR-0007…ADR-0015 содержат проектные решения, но не все означают реализацию.

## Сводка

| # | Пункт | Статус | Блокер | Где детали |
|---|---|---|---|---|
| OR-1/OR-2 | Gate API для agent mode | выполнено | — | ADR-0008/0009 |
| AG-5/AG-8 | Server-agent report MVP + workflow | выполнено | — | ADR-0009 §13 |
| AG-6/AG-9 | Triage, action log и audit push | не начато | AG-5 | ADR-0009 §13 |
| MM-1/MM-2 | Общий CLI `serve`/`sync`/`ci`/`agent` | выполнено | — | ADR-0014 §5 |
| MM-3/MM-5/MM-6 | Autonomous RO-agent, LLM tools, prompt, controller и лимиты | выполнено | — | ADR-0014/0015 |
| MM-7/MM-9 | Multi-mode Docker и тесты RO-agent | выполнено | — | ADR-0014 §5 |
| TP-PREP | Тестовый контур и утверждённый пакет TP-0001 | в работе | параметры стенда и утверждение | TP-0001 §6 |
| TP-EXEC | Выполнение TP-0001, отчёт и выбор модели | назначено Kimi | TP-PREP | TP-0001 |
| MM-4/MM-8 | RW demo и полная документация режимов | после TP-0001 | RO-agent | ADR-0014 |
| DB-1…DB-9 | PostgreSQL + auth-фундамент | выполнено | — | ADR-0012 |
| RSS-2…RSS-6/RSS-9 | Scan run observability MVP | после TP-0001 | нет | ADR-0011 |
| MCP-M-1…MCP-M-7 | Read-only MCP master | выполнено | — | ADR-0013/0015 |
| ADR-0007 | Per-branch state | Proposed, Фаза 3 | classic multi-version | ADR-0007 |
| ADR-0010 | RW-agent production | Пауза | un-pause критерии | ADR-0010 |
| MS-8 | DefectDojo/ASOC экспорт | отложено | нет | ADR-0004 §8 |
| P1/P2 | Semantic dedup (эмбеддинги) | план | нет | ADR-0001 §11 |
| SEV-1 | Verdict-aware severity escalation (TP secret/injection → critical) | open | после корпуса 300 | ниже |
| REV-1 | Режим переоценки (re-evaluation) по базе master с верификацией reuse | open | правила переоценки — открытый вопрос | ниже |

## Минимальный GAP до TP-0001

Цель — начать тестирование RO-agent без реализации RW, RSS и MCP-master.

1. **MM-1/MM-2:** единый `appsecgate-mcp` CLI; существующие `serve`, `sync`, `ci`
   сохраняют контракты. Тестовый сценарий использует `agent --mode=ro`, не `ci`.
2. **MM-3:** MCP-клиент, запуск `serve` child, цикл `scan → get_fix_context →
   triage → check_gate → report`; Markdown/JSON, exit `0/2`.
3. **MM-5/MM-6:** опциональный `openai`, LiteLLM/OpenAI-compatible конфигурация,
   неизменяемый system prompt, `AGENTS.md`/config как контекст, таймауты и лимиты.
4. **MM-7/MM-9:** запуск режимов из одного образа; mock-LLM, `:ro`, недоступность
   LLM/master, JSON-контракт и полный `make check`.
5. **TP-PREP:** `scenario.md`, env трёх моделей, `invoke.sh`, ground truth,
   `master_checks.py`, `gate_tests`, `eval.py`, схема отчёта, fault injection,
   хэши prompt и журналы. Пакет утверждает человек.

PostgreSQL (DB-1…DB-9) не блокирует Стадию 1: она выполняется на текущем SQLite
master. До параллельной Стадии 2 нужен PostgreSQL с проверкой конкурентной
идемпотентности. ADR-0011 полезен для наблюдаемости, но не входит в минимальный GAP:
`run_id` теста не следует выдавать за реализованный master `scan_run_id`.

## Назначение TP-0001

**Исполнитель:** Kimi — подготовка стенда, запуски, watchdog, master-проверки,
оценка, fix-and-resume и итоговый отчёт. **Утверждение пакета и приёмка:** человек.
Тестируется только `appsecgate-mcp agent --mode=ro`; классический hard-gate `ci`
и RW-agent в объект теста не входят. Ключевые пороги и две стадии сохранены.

## Release candidate guided-agent (заморожено 2026-11-05)

Пакет решений по итогам эксперимента (логи ClickHouse + прогоны g1…g5,
DeepSeek-сравнение, mock smoke T-01/T-04/T-07):

- **Guided — основной режим корпуса.** Free сохранён как опция для сильных
  моделей. Скан всегда завершается до старта LLM; scan-инструментов у модели нет.
- **Batching от output-бюджета:** `min(20, (llm_max_tokens//2)//120)` verdicts
  на запрос. Не привязано к конкретной модели.
- **Детерминированный prefetch:** `get_fix_context_batch` + dependency
  манифесты (до 400 строк, ≤20k chars) в каждый batch.
- **Bounded evidence reads:** `read_project_file` и master knowledge доступны
  до единственного `submit_verdicts` на finding, лимит 4 итерации на batch.
  Verdicts не пересматриваются, журнал append-only (ADR-0015 §4, important).
- **FP по неполноте доказательств запрещён** промптом; недостаток данных →
  NEEDS_REVIEW.
- **Retry-логика:** truncation/невалидный JSON → split batch пополам;
  частичный пропуск ID → повтор (depth-limited); одиночный невалидный →
  явный pending (`failed_findings`, `guided_incomplete`), не NEEDS_REVIEW.
- **Токен-бюджет:** превышение — ошибка только при pending; полный triage
  завершается с warning (ADR-0015 §10).
- **Ollama:** `FLASH_ATTENTION=1`, `KV_CACHE_TYPE=q8_0` (принят по parity),
  `PREFILL_CACHE=1`, `KEEP_ALIVE=-1`, `LOAD_TIMEOUT=20m`.
- **Эталоны:** CodeWiki 85/85 (175–186 сек), zep 256/256 (582–650 сек,
  ~0,5M tokens). DeepSeek-4.1 guided: те же покрытия в ~2× быстрее.
- **Инфраструктура:** `APPSECGATE_AGENT_MODE` проброшен в `invoke-docker.sh`;
  `BENCH_MODELS` переопределяем в `make experiment-dev-run`.
- `make check` зелёный: 535 mcp-server + 148 master (2 skipped) + 8 agent.

## Перед основным корпусом 300 (зафиксировано 2026-11-05)

- Основной режим — `--agent-mode=guided` (ADR-0015 §4): полное покрытие на
  development suite (CodeWiki 85/85, zep 256/256), free остаётся опцией.
- **Обязательно:** несколько валидационных прогонов с оптимизированной
  конфигурацией ollama до preflight. Раньше оптимизация была дефолтной,
  теперь параметры подобраны под конкретную модель (владелец стенда).
- **Выбрать тип KV cache: q4 или q8.** Критерий — совпадение verdicts с
  эталонными прогонами g2/g3b по finding_id (q4 дешевле по памяти, q8 точнее);
  при расхождениях берём q8. Выбор фиксируется в frozen run config вместе с
  параметрами ollama; timing-метрики до/после оптимизации несравнимы.
- Включение prefix caching влияет только на latency/cost, не на verdicts;
  в guided общий префикс мал (~10–15% prompt), поэтому это throughput-оптимизация,
  а не условие корректности эксперимента.
- Токен-бюджет guided: ~2k токенов на finding, `APPSECGATE_AGENT_MAX_TOKENS`
  с запасом (zep ≈ 0,5M).
- **Выполнено:** валидация ollama `FLASH_ATTENTION=1`, `KV_CACHE_TYPE=q8_0`,
  `PREFILL_CACHE=1`, `KEEP_ALIVE=-1` — g4/g5: verdicts совпали с эталоном
  (CodeWiki 85/85, zep 256/256, 0 failed). q8_0 принят.

## Ступени основного эксперимента и лимиты времени (2026-11-05)

Прогон разбивается на ступени с go/no-go между ними; переход дальше только
после разбора предыдущей ступени. Прогноз: 10–25 ч суммарно (1 GPU),
уточняется после ступени 1.

| Ступень | Содержание | Лимит | Критерий перехода |
|---|---|---|---|
| 0. Setup | docker-build/master-build, run config, master + knowledge + OSV, readiness-check | 2 ч | readiness зелёный |
| 1. Preflight + первые 20 | `experiment-agent300-preflight`, затем 20 репозиториев корпуса | 2 ч | ≥90% runs с полным покрытием; уточнённый прогноз по findings/repo и p95 |
| 2. Следующие 100 | основной корпус, часть 1 | 8 ч | доля failed/missing разобрана, нет системных багов |
| 3. Оставшиеся 180 | основной корпус, часть 2 | 14 ч | 300/300 отчётов |
| 4. Повторы | `experiment-agent300-repeat` (10 dev) | 1 ч | стабильность verdicts |
| 5. Отчёт | funnel, blind review, итог | 2 ч | — |

**Лимиты на уровне репозитория (уже реализованы, не менять без необходимости):**
- agent `--timeout=1800` (30 мин), внешний `timeout 35m` контейнера в
  `invoke-docker.sh`; превышение → явный `exit_reason=timeout`, не зависание.
- Токен-бюджет `APPSECGATE_AGENT_MAX_TOKENS`: ошибка только при pending.

**Завершение ступени/эксперимента по лимиту времени:**
- По достижении лимита ступени новые репозитории не запускаются; текущий run
  завершается своим `--timeout` или останавливается вручную.
- Незапущенные репозитории переносятся на следующий запуск: `run_agent300.py`
  выставляет `BENCH_RESUME=1`, и runs с готовым `report.json`
  (`report_generated`/`gate_block`) пропускаются; timeout/error перезапускаются.
- Каждая остановка фиксируется в отчёте ступени: сколько runs завершено,
  сколько перенесено, причина. Прерванный run не считается покрытым корпусом.

## Прочие направления

- AG-6/AG-9 относятся к отдельному `appsecgate-agent` и не заменяют MM-3.
- Semantic dedup P1/P2, SonarQube, дашборды и MS-8 не блокируют TP-0001.
- E2E classic CI-полигон ведётся отдельно от TP-0001 (ADR-0003 §9).

## REV-1: Re-evaluation mode (зарегистрировано 2026-11-06, правила — открытый вопрос)

Идея: отдельный режим агента, который работает не по свежему скану, а по базе
master — переоценивает накопленные вердикты и **верифицирует корректность
reuse**: если reuse подставил старый вердикт, а условия изменились (модель,
промпт, правила, CVE-снапшот, контекст), режим перепроверяет находку и
фиксирует расхождение.

Зачем: reuse делает повторные прогоны почти бесплатными (в корпусе до 100%
вердиктов без LLM), но ценой «замораживания» прошлых решений модели.
Re-evaluation — это аудит этого замораживания: выборочная или полная
переоценка показывает, какая доля reused-вердиктов воспроизводится, а какая
была дрейфом (vibetunnel 9/86 — первый сигнал).

**TTL/revision/provenance accepted on 2026-11-06 (working tree, ADR-0017):**
the latest verdict per fingerprint is reused only while younger than `reuse_ttl`
(default `1w`) and has numeric confidence. Expired and legacy records without
confidence return to triage. Cross-run revisions are append-only with
`supersedes_verdict_id`, `revision_reason`, model/actor, prompt, ruleset and
per-rule provenance. Controlled `rev1v3` validation on structlog/aitextgen passed:
5 fresh reused verdicts with zero LLM/events, 2 TTL supersedes and 3 legacy
supersedes. Severity escalation remains disabled pending human calibration;
bitcore sizing and AIWriteX failures remain corpus blockers.

**Future explicit trigger:** add `--force-reevaluate` (and a matching env flag)
to bypass TTL freshness for every reuse candidate while still reading prior
verdicts and writing `supersedes_verdict_id` with `revision_reason=manual`.
Unlike `--no-reuse-verdicts`, it preserves retrospective lineage. It remains a
separate future task and was not part of the controlled rev1v3 validation.

**Remaining re-evaluation questions:**

- Что триггерит переоценку: смена модели/промпта (prompt_sha256), смена
  ruleset_hash, новый CVE-снапшот, истечение TTL вердикта, случайная выборка
  (аудит n%)?
- Объём: все находки проекта, только TP (самые дорогие ошибки), только
  reused, только старше N дней?
- Что считается расхождением: смена verdict, смена severity/confidence
  (если REV-1 заведётся после SEV-1 варианта B), изменение обоснования?
- Куда писать результат: новая ревизия вердикта append-only (старое не
  затирается) vs отдельный журнал аудита.
- Взаимодействие с gate: может ли переоценка отменить прошлый gate_block/
  report_generated ретроактивно или только влиять на будущие runs.

Связано: SEV-1 (confidence как вход для правил переоценки), ADR-0015 §4
(journal append-only — verdicts не пересматриваются внутри run; REV-1 это
внешний пересмотр между runs, инвариант не нарушается).

## SEV-1: Verdict-aware severity escalation (зарегистрировано 2026-11-06)

Наблюдение из корпуса agent300: сканерный severity описывает подозрение, но не
учитывает вердикт агента. Подтверждённый секрет (работающий credential) или
подтверждённая инъекция семантически являются critical, оставаясь high в отчёте.

Предлагаемая модель (этап формирования report/gate, не сканер и не агент):

- `effective_severity(finding, verdict, config)` как отдельная функция; сырой
  severity сканера сохраняется для диагностики.
- Эскалация задаётся **только через конфиг, помаппингово по категориям**
  находки (`secret`/`sast`/`sca`/`iac`/`license`), никаких захардкоженных
  списков в коде:

  ```yaml
  severity_escalation:
    secret: critical    # TP по gitleaks/trufflehog → critical
    sast: critical      # TP по injection-классам → critical (см. rule_classes ниже)
  ```

- Опциональный фильтр классов правил внутри категории
  (`severity_escalation_rule_classes.sast: [sqli, eval, deserialization,
  command-injection, ssrf]`) — чтобы не эскалировать весь SAST скопом.
- Применяется только к verdict=TRUE_POSITIVE. NEEDS_REVIEW не повышается
  (не подтверждено); FP severity не играет.
- Default: пустой маппинг (эскалация выключена), поведение как сейчас;
  включение — явным полем в config.yaml, валидируется `update_config`.

**Вариант B — ADR-0018 (Proposed):** numeric confidence 0…100 признан legacy из-за
anchor bias. Новый протокол использует `confidence_level`
(`high/medium/low/speculative`) и per-mode `evidence_basis` с детерминированной
edge-валидацией и downgrade journal. `high` означает проверяемый тип evidence,
а не самооценку модели. Numeric события остаются в append-only истории, но в новый
reuse не входят и не мигрируются.

Эскалация severity — ответственность **master**, не edge. Master re-валидирует
события и создаёт append-only escalation decisions с версией policy, используя
confidence/evidence, cross-project history, human labels, CVE/reachability и
deployment evidence. Решения не перезаписывают исходные verdict events. При
недоступном master edge сохраняет базовый severity (fail-deferred).

Стартовый Mode A: SAST `direct_snippet`, Secrets `direct_snippet_credential`,
CVE `manifest_version_match`, IaC `policy_rule_direct`. Mode B
(`file_verified`/`reachability_verified`) отложен из-за prefill. Эскалация остаётся
выключенной до слепой человеческой калибровки на master. См.
`docs/adr/ADR-0018-evidence-based-confidence.md`.

Оба варианта совместимы: A — частный случай B с неявным confidence=high.

Предусловия перед включением:

1. Ручная выборочная валидация TP-вердиктов на secret-эвристиках (vibetunnel
   drift 9/86, gitleaks generic даёт TP на плейсхолдерах) — иначе critical-шум.
2. Офлайн-пересчёт gate-решений корпуса 300 по готовым report.json (вердикты
   уже есть, миграция данных не нужна).
3. Оценка влияния на долю gate_block в корпусе.

## Ссылки на закрытые задачи

T1…T15, CI-1…CI-7, MS-1…MS-7 — `docs/history/phase-1-2-completed.md`.
