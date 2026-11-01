# TP-0001: RO-agent с локальными LLM и master

| Поле | Значение |
|------|----------|
| **Версия** | 2.0 |
| **Статус** | Test Plan — требуется реализация MM и утверждение пакета |
| **Дата** | 2026-11-01 |
| **Объект** | `appsecgate-mcp agent --mode=ro` (ADR-0014), LiteLLM и master |
| **Исполнитель** | Kimi — подготовка, оркестрация, надзор и отчёт |
| **Приёмка** | Человек — утверждение пакета, ground truth и итогового отчёта |
| **Модели** | Qwen, GLM, Gemma4 через OpenAI-compatible LiteLLM |
| **Связанные** | ADR-0001/0004/0006/0009/0011/0012/0014, `deploy-master.md` |

## 1. Назначение и границы

Тест проверяет две гипотезы:

1. RO-agent стабильно выполняет `scan → контекст → LLM-триаж → check_gate →
   report → sync`, корректно обращается с master, suppressions, policy и сбоями.
2. Качество FP/TP-триажа и предложенных патчей достаточно для выбора модели и
   масштабирования на 100 репозиториев.

**Только LLM-агент.** Классический `appsecgate-mcp ci` не является runner и не
подменяет agent. `check_gate` advisory: `should_fail=true` не обязан завершать
agent с блокирующим exit code. Штатные exit codes агента: `0` — отчёт сформирован
(включая gate block и warnings), `2` — инфраструктурная ошибка. Exit `1` не
используется как признак findings.

RO-agent не изменяет проект, не применяет патчи и не создаёт suppressions по
собственному решению. Патч — артефакт; проверку выполняет Kimi на копии репозитория.
Suppression в тестовых сценариях создаёт человек или детерминированная фикстура,
не LLM. RW, RSS/scan_run, MCP-master и качество самих сканеров вне объёма.

## 2. Цели и приёмка

| # | Цель |
|---|------|
| G1 | Полный цикл RO-agent и корректные exit `0/2` |
| G2 | Advisory gate, suppressions, master policy и fail-closed |
| G3 | Полнота, своевременность и идемпотентность master |
| G4 | Качество триажа и предлагаемых патчей |
| G5 | Стабильность на 100 репозиториях |
| G6 | Работоспособность на всех трёх моделях |
| G7 | Обоснованный выбор победителя |

- **A1:** ≥95% проходов Стадий 1A/1B без `hung`/`timeout`/`model_crash`.
- **A2:** `ci_correctness ≥ 0.9` у победителя; название метрики сохранено, но это
  доля пройденных agent gate tests, а не classic CI.
- **A3:** `master_completeness=1.0` на Стадии 1, ≥0.98 на Стадии 2 с документированными исключениями.
- **A4:** `sync_idempotency_failures=0` штатно; ≤1% при инжекции сбоев.
- **A5:** `fail_closed_pass=1/1` на каждой модели при обязательном master.
- **A6:** ≥90 репозиториев Стадии 2 обработаны и доставлены на master.
- **A7:** отчёт содержит разделы «Доставка на master» и «Дефекты и улучшения».
- **A8:** к концу 10 циклов для **каждой** модели `ci_correctness≥0.9`,
  `master_score≥0.9`, стабильность≥0.95.
- **A9:** после каждого прогона есть краткий отчёт и статус времени `green/yellow/red`.
- **A10:** все fix-and-resume задокументированы; после каждого — полный повтор цикла.
- **A11:** Стадия 2 не начинается до A8.
- **A12:** второе мнение Kimi покрывает ориентировочно ≤10% находок Стадии 2;
  превышение анализируется, но не блокирует тест.
- **A13:** итоговый отчёт содержит фактические метрики экономии токенов Kimi.

## 3. Стенд и роли

```text
Kimi (оркестратор/watchdog/eval/master_checks)
  └─ invoke.sh → appsecgate-mcp agent --mode=ro --output-format json
                    ├─ child serve (MCP stdio; проект :ro)
                    ├─ LiteLLM → Qwen | GLM | Gemma4
                    └─ sync → master REST → SQLite (Стадия 1)
                                           PostgreSQL (Стадия 2)
```

- LLM не имеет прямого доступа к master и не видит ground truth/чужие прогоны.
- Agent имеет сеть только к LiteLLM и master; MCP-тулы не выполняют HTTP сами.
- Master на Стадии 1 — текущий SQLite WAL. До параллельной Стадии 2 внедряется
  PostgreSQL по ADR-0012; ClickHouse и MCP-master не требуются.
- Отчёты, логи, вердикты и патчи хранятся отдельно от master.
- Kimi не пишет альтернативный цикл триажа и не меняет prompt агента.
- Человек утверждает пакет, `T_budget`, `K`, ground truth и итог.

## 4. Минимальная готовность

До подготовки стенда нужны MM-1/MM-2 (CLI), MM-3 (RO-agent), MM-5/MM-6
(OpenAI-compatible client, prompt, контекст, лимиты), MM-7/MM-9 (образ и тесты).
MM-4/RW, ADR-0011 и ADR-0013 не блокируют тест. Подробности — `../open-tasks.md`.

Обязательные свойства runner:

1. `agent --mode=ro` работает на `:ro`, вызывает MCP `scan_project`/`scan_diff`,
   `get_fix_context_batch`, `check_gate`; `read_files` не существует и не используется.
2. JSON содержит `run_id`, модель, findings/verdicts, предложенные патчи,
   `GateSummary`, tool/action log, usage, warnings, duration и exit reason.
   Тестовый `run_id` — не master `scan_run_id` из нереализованного ADR-0011.
3. После agent вызывается существующий `appsecgate-mcp sync`; при заданном
   обязательном master сбой sync/final pull → exit `2`. Локальный запуск без
   master допустим только вне приёмочных прогонов.
4. LLM unavailable/invalid protocol, превышение внешнего timeout и инфраструктурный
   сбой → классифицируемый exit `2`; gate block сам по себе → exit `0`.
5. Prompt версионируется и хэшируется; RW-флаги и запись в проект не используются.

## 5. Пакет тестирования

Kimi предъявляет человеку до запуска:

| Артефакт | Содержимое |
|----------|------------|
| `scenario.md` | Точные CLI/env, последовательность agent→sync, таймауты, циклы и gate tests |
| `ci_config/<model>.env` | Имя сохранено для совместимости пакета; LiteLLM и master credentials |
| `invoke.sh` | Только запуск agent/sync, timeout/retry/log rotation; без своего триажа |
| `repos/stage1_project.json` | Проект, commit, ground truth, difficulty/critical |
| `repos/stage2_list.json` | 100 репозиториев с фиксированными SHA и pre-flight |
| `master_checks.py` | D1–D8; ground truth недоступен |
| `gate_tests/` | T-01…T-08 для agent + `check_gate` |
| `eval.py`, `schema.json` | Метрики и валидация отчёта каждого прогона |
| `fault_injection.md` | Master down/5xx/401, policy, обрыв sync |
| `prompts_hash.txt` | Эталонный хэш prompt и версия runner |
| `improvements_log.json` | Журнал fix-and-resume |
| `resources.json` | GPU/RAM/parallelism и источники LiteLLM usage |

Утверждение требует: изоляцию LLM от master, отсутствие ground truth в prompt,
уникальные project-scoped ключи, чистые data-dir, фиксированные SHA, расписание
T-01…T-08, `T_budget`, `K` и дизайн экономии Kimi. PostgreSQL readiness отдельно
проверяется перед Стадией 2.

Ground truth готовит Kimi через скан и `get_fix_context_batch`; человек валидирует
20% случайных и все спорные находки. Используется только в `eval.py`. Для Стадии 2
100 репозиториев фиксируются по commit SHA и проходят pre-flight scan.

## 6. Программа

### 6.1. Стадия 1A — 10 циклов × 3 модели

Каждый цикл последовательно запускает Qwen, GLM, Gemma4 на одном проекте. Каждый
прогон получает чистый edge data-dir, новый `project_id/run_id` и credentials.
Повтор после fix-and-resume перепроходит весь цикл для всех моделей.

Один проход:

1. `invoke.sh` запускает `agent --mode=ro` с полным проектным сканом и JSON.
2. Agent получает findings и код через MCP, выполняет LLM-триаж, формирует
   объяснения/патчи, вызывает `check_gate(policy=warn)` и завершает отчёт.
3. Runner синхронизирует edge с master. Kimi не добавляет свои findings в поток.
4. Kimi выполняет D1–D7, собирает LiteLLM usage, логи и артефакты, считает F1
   и качество патчей на копии репозитория, обновляет `progress.json`.
5. Kimi выдаёт краткий отчёт, тренд, bottleneck flags и оценку времени.

Проект не меняется между прогонами. Применение патча выполняется только в отдельной
копии для оценки, не в исходном стенде. Стадия 1A не создаёт remote suppression:
это отдельные фикстуры Стадии 1B.

### 6.2. Стадия 1B — agent gate tests

Полные T-01…T-08 на каждой модели — циклы 1, 5, 10; T-01/T-04/T-07 — остальные.
Итого 135 прогонов. Для детерминированной проверки gate допускается mock-LLM с
фиксированным ответом; такие прогоны идут в `ci_correctness`, но не в F1 модели.

| ID | Сетап и действие | Ожидание |
|----|------------------|----------|
| T-01 | Shown TP на master, повторный agent scan, `block_on_unresolved_local=true` | `should_fail=true`, reason `unresolved_local`; agent exit 0; D1 |
| T-02 | FP и человек/fixture создали допустимый local/remote suppression | Finding не показана, `should_fail=false`, exit 0; D6 |
| T-03 | Kimi применил предложенный патч на копии; verify + повторный scan | Finding FIXED/отсутствует, gate pass, lifecycle D5; agent не писал проект |
| T-04 | Master обязателен и недоступен | Agent/sync завершается exit 2 в пределах timeout; D8 |
| T-05 | Master policy изменила gates; выполнен pull до запуска | Новый `GateSummary` соответствует policy; D7 |
| T-06 | Master содержит CI/global suppression для fingerprint | После pull finding отфильтрована, gate pass; D6 |
| T-07 | Два agent прогона с тем же `run_id` и повторный push | Дублей events/findings нет; D3 |
| T-08 | Обычный проект с blockable TP, `policy=block` | `should_fail=true`, корректный JSON, agent exit 0 |

T-01/T-08 проверяют advisory gate, а не блокирующий exit classic CI. Для T-03
верификация и lifecycle выполняются через MCP/sync на копии; LLM не объявляет FIXED
самостоятельно.

### 6.3. Стадия 2 — 100 репозиториев победителем

1. Перед стартом: A8, утверждённый победитель, PostgreSQL и concurrency checks.
2. Parallelism = минимум GPU/RAM/LiteLLM/agent/master limits.
3. Timeout репозитория `max(30 мин, 3×expected_scan_sec)`; после каждого D1–D7.
4. 10 репозиториев повторяются; 10 получают сетевые сбои; 10 — remote suppressions;
   10 — обязательный недоступный master.

| ID | Проверка | Ожидание |
|----|----------|----------|
| T-09 | Обрыв sync/5xx и повтор на 10 репозиториях | Outbox доезжает, 0 дублей |
| T-10 | Два прогона 10 репозиториев | Lifecycle без склеивания run/project |
| T-11 | Remote suppression + повторный scan | Finding не показывается |
| T-12 | Master down на 10 репозиториях | Exit 2 у всех |

## 7. Надзор, метрики и fix-and-resume

После каждого прогона Kimi считает `T_remaining` и `T_estimate_remaining` с буфером
на исправления. `green`: оценка ≤80% остатка; `yellow`: ≤100%; `red`: >100% —
остановка и решение человека. Отчёт 5–10 строк содержит run/model/status, exit,
gate, F1/patch metrics, D1–D7, tokens/duration, trend, bottleneck и time budget.

Watchdog фиксирует отсутствие прогресса >2 минут, внешний timeout процесса,
LLM/MCP/network stall. Причины: `agent`, `llm`, `mcp`, `network`; инфраструктурные
зависания не приписываются качеству модели.

Веса победителя: 0.30 F1 + 0.20 patch quality + 0.30 `ci_correctness` +
0.15 `master_score` + 0.05 стабильность. Дисквалификация при `ci_correctness<0.8`,
`master_score<0.8` или стабильности<0.8. Стабильность — доля успешных проходов;
в отчёте также отдельно указывается доля сбоев.

Patch quality включает apply rate на копии, закрытие finding после повторного scan
и рубрику Kimi. F1 считается для FALSE_POSITIVE и отдельно для критичных TP.
На Стадии 2 качество без ground truth оценивается косвенно по выборке и повторам.

Fix-and-resume допустим только для воспроизводимого дефекта runner/MCP/master,
влияющего на A8. Prompt не меняется, runner не подменяется. Человек утверждает
карточку; лимит `K`; цикл повторяется полностью плюс регрессионный цикл. Плохое
качество самой модели — результат теста, а не повод менять prompt.

На Стадии 2 Kimi читает агрегаты, а не все вердикты. Второе мнение — плановые 5%
и триггеры: FP>90%, FP<10%, несоответствие gate, edge/master divergence, сбой,
расхождение повторов. Используются кэш verdicts, короткий контекст через
`get_fix_context_batch`, батчинг и дельта-анализ. Расход Kimi наблюдается без
автоматической остановки; D1–D8 и T-09…T-12 не сокращаются.

## 8. Master-проверки

| # | Проверка | Порог |
|---|----------|-------|
| D1 | Edge shown findings == master findings проекта | 100% / ≥98% |
| D2 | `master_received_at − edge_shown_at`, p50/p95 | p95 <5 мин |
| D3 | Повторный push не создаёт дублей | 0 |
| D4 | Fingerprint edge == master | 100% |
| D5 | Lifecycle соответствует ADR-0006 | Нет нарушений |
| D6 | Pulled suppression применён в следующем agent scan | 100% целевых кейсов |
| D7 | Pulled policy применён в `check_gate` | 100% целевых кейсов |
| D8 | Обязательный master недоступен → exit 2 | 1/1 |

`master_score` — доля D1–D7, применимых к прогону; D2 измеряется по timestamps
edge и audit/event master. D6/D7 не симулируются на прогонах без соответствующей
фикстуры. D8 отдельно. Для каждого прогона проверяется отсутствие доступа LLM к
master на уровне стенда, а не вызовом `master_checks.py` от имени LLM.

## 9. Артефакты и итог

На прогон: JSON по schema, полный agent/sync log, snapshots edge DB, verdicts и
патчи, tool/action log, LiteLLM usage, D1–D7, progress/time budget. Агрегаты:
`progress.json`, `improvements_log.json`, master/CI aggregates, Kimi token usage,
verdict cache, second-opinion samples и режимы надзора.

Итоговый отчёт: executive summary; методология; сравнение моделей; gate tests;
тренд и fix-and-resume; масштаб; **доставка на master**; **дефекты и улучшения**;
бюджет; **экономия токенов Kimi**; ограничения; рекомендации; приложения.

Тест пройден при A1–A13, утверждении человеком и отсутствии незадокументированных
исключений. Недостижение A8, <90 доставленных репозиториев, нарушение D3/D8 или
систематические agent hangs — непроход. Невозможность запустить RO-agent с локальной
LLM — блокер теста, а не отрицательный результат модели.
