# Handoff-промпт: SEV-1 вариант B (confidence в submit_verdicts) до корпуса 300

Дата: 2026-11-06. Репозиторий: appsecgate-mcp (корень). Корпус agent300
**намеренно остановлен** на 17/300 (оркестратор убит, контейнеры остановлены)
и ждёт эту доработку. Не перезапускай корпус, пока не пройдут все шаги ниже.

## Задача

Добавить опциональное поле `confidence` (`"low" | "medium" | "high"`) в вердикты
агента, чтобы последующая эскалация severity (SEV-1, см. `docs/open-tasks.md`)
применялась только к TP с высокой уверенностью. Полный контекст решения —
`docs/open-tasks.md`, секции «SEV-1» (вариант B помечен предпочтительным) и
«REV-1».

## Что сделать

1. **Модель вердикта.** Найти, где парсится/валидируется verdict агента:
   `mcp-server/src/appsecgate_mcp/agent/guided.py` (submit_verdicts, функция
   разбора batch-ответа) и `mcp-server/src/appsecgate_mcp/agent/guided_sched.py`.
   Поле опциональное; при отсутствии — `confidence=None`, не ошибка.
   Валидные значения только low/medium/high; иное значение — трактовать как
   отсутствие поля (не ронять батч).
2. **Промпт.** В guided-промпте (искать в `mcp-server/src/appsecgate_mcp/agent/`
   — system prompt / template; свериться с `prompts_hash.txt` в
   `experiments/tp-0001/`) описать шкалу:
   - `high` — verdict подтверждён конкретным evidence (код/секрет/манифест
     увиден и однозначно читается);
   - `medium` — verdict следует из сильных косвенных признаков;
   - `low` — слабые сигналы; при low по возможности предпочесть NEEDS_REVIEW.
   Формулировки короткие; промпт не должен менять существующие правила
   вердиктов (запрет FP по неполноте доказательств сохранить).
3. **Экспорт.** `confidence` должен попасть в `report.json` (список `verdicts`)
   и в журнал/выгрузку на master, если вердикты туда пишутся — проверить
   `mcp-server/src/appsecgate_mcp/storage/` и `sync/`.
4. **Тесты.** Добавить в существующие тесты guided/guided_sched кейсы:
   verdict с confidence парсится; без confidence — None; невалидное значение —
   None и батч не падает. Не менять существующие снапшоты поведения.
5. **Документация.** `docs/open-tasks.md` SEV-1: отметить, что вариант B
   реализован (дата, коммит). README при необходимости.

## Инварианты и ограничения (обязательно)

- См. `AGENTS.md`: инварианты 1–6 не нарушать; `submit_verdicts` — расширение
  только опциональным полем, существующие вызовы без него работают как раньше.
- `from __future__ import annotations`, ruff line-length 100.
- Проверка: только `make check` (должно быть зелёно: 542+148+8 и новые тесты),
  `make format`. Никаких прямых `uv run pytest`/`ruff`.
- Файловые лимиты: `.py` ≤ 400 строк и ≤ 20 КБ — если guided.py упирается,
  выносить в подмодуль.

## После реализации — parity gate (обязательно до корпуса)

Изменение промпта может сдвинуть вердикты. Прогнать эталоны и сравнить по
finding_id с существующими артефактами:

1. `make docker-build` (канонический тег, без ручных тегов).
2. Эталонные прогоны: CodeWiki (эталон 85/85, ~180 с) и zep (эталон 256/256,
   ~640 с) — существующие результаты в `experiments/tp-0001/artifacts/` искать
   по `agent-sched-*-CodeWiki` / `*-zep` либо запустить через
   `make experiment-gate-smoke` / benchmark-скрипты (см. Makefile и
   `experiments/tp-0001/SCRIPTS.md`).
3. Критерий: полное покрытие (85/85, 256/256), 0 failed_findings, расхождение
   вердиктов по общим finding_id ≤ 2 на репо. Больше — откатить изменение
   промпта (оставить поле в коде, убрать упоминание из промпта) и остановиться
   для разбора.

## Перефриз и перезапуск корпуса (строго в этом порядке)

1. `make experiment-run-config` — пересоздаст frozen config (image id,
   prompt_sha256, knowledge_cutoff=now). ВАЖНО: `parallelism` уже = 1 и
   `agent_mode=guided-sched` в `prepare_agent_run_config.py` — не трогать.
2. `make experiment-cve-prepare CVE_ARGS='--pattern "artifacts/agent300-preflight-gemmaq3-p1-*/report.json"'`
   — обязательно ПОСЛЕ run-config (проверка readiness требует
   knowledge_cutoff ≤ fetched_at). Кавычки обязательны (glob не должен
   раскрываться shell).
3. `make experiment-readiness-check` — должен быть зелёный.
4. Если менялся `parallelism` (не должен): маппинги ключей в postgres имеют
   `ON CONFLICT DO NOTHING` — потребуется UPDATE таблицы `api_keys` в
   контейнере appsecgate-postgres (рецепт в истории сессии 2026-11-06;
   ключи: `experiments/tp-0001/runtime/agent300-keys.json`).
5. Удалить артефакты недоехавшего прогона:
   `rm -rf experiments/tp-0001/artifacts/agent300-gemmaq3-p1-*`
   (это 17 репо старого промпта; master-вердикты от них остаются и лягут
   в reuse — это нормально, fingerprint-матчинг).
6. Запуск ТОЛЬКО через make (напрямую `python3 run_agent300.py` теряет
   `RESEARCH_SEMGREP_RULES=1` и external-правила не монтируются):
   `setsid nohup make experiment-agent300-run > experiments/tp-0001/runtime/agent300-run.log 2>&1 &`
7. Проверить в первом контейнере: `docker inspect` → env содержит
   `APPSECGATE_RULES_DISTRIBUTION_MODE=commercial` и
   `APPSECGATE_SCANNER_TIMEOUT=900`, примонтирован
   `runtime/research-rules/rules → /home/appsecgate/.appsecgate-mcp/rules:ro`.

## Контекст уже сделанного (не переделывать)

- Образ с external-правилами и фиксом таймаута: `APPSECGATE_SCANNER_TIMEOUT`
  (env, дефолт 120) в `mcp-server/src/appsecgate_mcp/server/session.py`,
  900 с проброшено в `experiments/tp-0001/invoke-docker.sh`.
- Master: `appsecgate-agent300-master` + postgres запущены, ключи в postgres
  актуальны для p1. CVE: 268 импортировано.
- Мониторинг корпуса (cron раз в 15 мин) был удалён при остановке — после
  перезапуска корпуса пересоздать.
- Незакрытые хвосты: битый `artifacts/agent-sched-p4-gemmaq3-p1-PilotDeck/report.json`
  (прерванный бенчмарк, разобрать/удалить), vibetunnel drift 9/86 (к разбору),
  молчаливый `errors=[]` при spawn timeout сканера (кандидат на issue).

## Приёмка

1. `make check` зелёный.
2. Parity gate пройден (CodeWiki, zep).
3. Readiness зелёный на новом freeze.
4. Корпус запущен через make с external-правилами и мониторингом.
