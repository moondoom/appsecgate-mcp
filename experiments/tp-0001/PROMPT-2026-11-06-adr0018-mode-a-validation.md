# Handoff: ADR-0018 Mode A — массовая валидация и confidence calibration

Дата: 2026-11-06. Репозиторий: appsecgate-mcp (корень).

## Зафиксированное состояние

Git commits:

- `329f222` — TTL verdict re-evaluation and provenance.
- `4507e68` — Implement evidence-based confidence mode A.

Последний `make check`: 569 mcp-server + 149 master (+2 PostgreSQL skip) + 8 agent
— зелёно. Controlled `rev4` E2E: 5 fresh reused, 2 TTL revisions, 3 legacy
revisions, `experiments/tp-0001/artifacts/rev4-validation.json` имеет
`passed=true`.

Обязательно прочитать:

- `docs/adr/ADR-0018-evidence-based-confidence.md`
- `docs/adr/ADR-0017-ttl-verdict-reevaluation-experiment.md`
- `docs/open-tasks.md`, REV-1 и SEV-1
- `mcp-server/src/appsecgate_mcp/agent/verdict_validator.py`
- `mcp-server/src/appsecgate_mcp/agent/reuse.py`
- `mcp-server/src/appsecgate_mcp/agent/guided_sched.py`
- `appsecgate-master/src/appsecgate_master/contracts/verdict_validation.py`

## Что уже реализовано

- `confidence_level=high|medium|low|speculative`, per-mode `evidence_basis`.
- Edge downgrade с `model_confidence_level/model_verdict/downgrade_reason`.
- Master re-validation; invalid high/FP не принимается.
- Edge проверка SHA-256 evidence_quote; master проверяет наличие/формат, потому что
  quote уже redacted.
- Per-mode prompts/hashes и `revision_reason=prompt_updated`.
- Scheduler группирует однородные mode-batches по `(mode, lane)` для prompt cache.
- Numeric confidence остаётся только в старой append-only истории и не участвует в
  новом fresh reuse. Историю не переписывать и не удалять.
- Severity escalation НЕ реализована и НЕ включена. Mode B
  (`file_verified`/`reachability_verified`) не включать.

## Границы

1. Основной корпус 300 НЕ запускать.
2. Severity escalation НЕ включать: сначала blind human calibration на master.
3. Не менять protocol/prompt до получения baseline: сначала измерить Mode A.
4. Не повторять прошлые run IDs/labels. Использовать новый prefix `adr18` и новые
   artifacts; append-only дедуп не должен смешивать попытки.
5. Bitcore и AIWriteX — operational blockers, а не повод молча увеличить timeout
   или изменить policy. Основной corpus остаётся закрыт до отдельного решения.

## Порядок работ

### 1. Проверка baseline

```bash
make check
make docker-build
make docker-master-build
make experiment-agent300-master
make experiment-run-config
REV1_RUN_PREFIX=adr18smoke make experiment-rev1-validation
```

Требуется `passed=true`. Если падает — сначала разобрать причину, не ослаблять gate.
Обратить внимание на уникальность run IDs и отсутствие `rejected:edge_validator`.

### 2. Подготовить 10-run tooling до запуска

Текущий `experiment-reevaluation-run` использует старый `agent300review` label и
может пропустить существующие reports через `BENCH_RESUME=1`. Не удалять старые
artifacts. Добавить отдельный label/target, например `agent300adr18`, с:

- теми же 10 repos из `REPEAT`;
- новыми artifacts;
- `BENCH_PROJECT_ID_LABEL=agent300` для eligible history;
- `reuse_ttl=1h`;
- knowledge cutoff, который НЕ скрывает новые events между повторными runs;
- `parallelism=1`, `guided-sched`, external rules.

Обновить collector для categorical protocol. Numeric confidence в новой
статистике не использовать. Все изменения проверять через `make check`.

### 3. Прогнать 10 development repositories

Запуск только через новый Make-target. Дождаться всех 10 reports. Собрать structured
JSON/Markdown статистику, не восстанавливать метрики из текстовых логов.

По каждому repo и aggregate показать:

- raw/unique findings, coverage, missing/failed;
- TP/FP/NR;
- reuse candidates/reused/re-evaluated;
- revision reasons: ttl_expired, legacy_confidence_missing, prompt_updated;
- confidence_level по mode;
- evidence_basis по mode;
- downgraded count и downgrade_reason;
- evidence_reads 0/>0;
- prompt_mode/prompt_sha256, ruleset/rule hashes;
- `rejected:edge_validator` и master sync errors;
- verdict drift по общим finding_id с предыдущей серией.

Критерии механики: 0 invalid high после edge/master validation, 0 numeric
confidence в новых events, 0 смешанных mode-batches. Покрытие и failures указать
фактически, не приписывать их confidence без анализа.

### 4. Bitcore и AIWriteX

Обновить `experiments/tp-0001/analyze_rev1_operations.py` под новые artifacts и
разобрать:

- bitcore: темп, inventory, timeline, loop/stall, sizing/resume. В прошлой серии
  441/958, 15.63 verdict/min, continuous progress, timeout 1800 s.
- AIWriteX: оба failed IDs в одном minified `workerMain.js`, 8 batch retries,
  217374 tokens. Проверить воспроизводимость large-context/protocol failure.
- Не применять sizing/timeout fix до документированного решения владельца.

### 5. Blind human calibration на master

Сформировать НОВЫЙ review bundle по categorical events, не переиспользовать numeric
`rev1-confidence-review.json` как ground truth. Стратификация:

- SAST / Secrets / CVE / IaC;
- evidence_reads 0/>0;
- confidence_level и evidence_basis;
- обязательно low/speculative кандидаты и downgrade cases.

Человек сначала ставит verdict + confidence_level + evidence_basis, не видя ответ
модели. Затем на master посчитать:

- accuracy per category/mode;
- reliability confidence_level × human correctness;
- false escalation rate (отдельно для critical);
- downgrade distribution;
- high без high-capable basis (должно быть 0);
- high-accuracy и anchor-bias distribution per mode.

Критерии ADR-0018 применять заранее, без подгонки после результатов. Если human
labels не получены — калибровка НЕ завершена, escalation остаётся выключенной.

### 6. Отчёт и остановка

Обновить ADR-0018 фактическими результатами Mode A и operational blockers. Не
переводить его в Accepted для severity escalation без human calibration. Отдельно
показать, подтверждены ли protocol/serialization/reuse.

Остановиться на review результатов. Не реализовывать Mode B, escalation policy,
`--force-reevaluate`, resizing corpus или основной 300 без явного следующего
решения владельца. Создать следующий handoff с путями artifacts, метриками,
failed gates и commit hashes.

## Definition of done для этой сессии

1. `make check` зелёный.
2. Controlled smoke `passed=true`.
3. Все 10 reports имеют structured categorical statistics.
4. Есть фактические per-mode confidence/basis/downgrade/reuse таблицы.
5. Bitcore и AIWriteX классифицированы по данным.
6. Human calibration либо выполнена с метриками, либо явно помечена как не
   выполненная из-за отсутствия labels.
7. ADR и handoff обновлены; работа остановлена на review.
8. Основной corpus и severity escalation не запущены.
