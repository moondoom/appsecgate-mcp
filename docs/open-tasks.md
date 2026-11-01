# Открытые задачи

> Активные пункты на 2026-11-01. Закрытые задачи — `docs/history/phase-1-2-completed.md`,
> детали реализации — `docs/history/implementation-notes.md`.
> Дизайн-решения — `docs/adr/`.

## Фактическое состояние

- Фаза 1 и технические этапы CI-1…CI-7, MS-1…MS-7 завершены.
- В MCP зарегистрировано 15 тулов; `check_gate` реализован (OR-1).
- `GET /v1/findings` поддерживает фильтры `state`, `branch` и `commit` (OR-2).
- `appsecgate-agent` реализует только детерминированный report MVP без LLM.
- Master работает на SQLite WAL; PostgreSQL, MCP-master и `scan_run` не реализованы.
- `appsecgate-mcp agent --mode=ro` реализован; `appsecgate-mcp ci` — отдельный hard-gate без LLM.
- ADR-0007…ADR-0014 содержат проектные решения, но не означают реализацию.

## Сводка

| # | Пункт | Статус | Блокер | Где детали |
|---|---|---|---|---|
| OR-1/OR-2 | Gate API для agent mode | выполнено | — | ADR-0008/0009 |
| AG-5/AG-8 | Server-agent report MVP + workflow | выполнено | — | ADR-0009 §13 |
| AG-6/AG-9 | Triage, action log и audit push | не начато | AG-5 | ADR-0009 §13 |
| MM-1/MM-2 | Общий CLI `serve`/`sync`/`ci`/`agent` | выполнено | — | ADR-0014 §5 |
| MM-3/MM-5/MM-6 | RO-agent, OpenAI-compatible LLM, prompt и лимиты | выполнено | — | ADR-0014 §5 |
| MM-7/MM-9 | Multi-mode Docker и тесты RO-agent | выполнено | — | ADR-0014 §5 |
| TP-PREP | Тестовый контур и утверждённый пакет TP-0001 | в работе | параметры стенда и утверждение | TP-0001 §6 |
| TP-EXEC | Выполнение TP-0001, отчёт и выбор модели | назначено Kimi | TP-PREP | TP-0001 |
| MM-4/MM-8 | RW demo и полная документация режимов | после TP-0001 | RO-agent | ADR-0014 |
| DB-1…DB-9 | PostgreSQL + auth-фундамент | до Стадии 2 TP-0001 | нет | ADR-0012 |
| RSS-2…RSS-6/RSS-9 | Scan run observability MVP | после TP-0001 | нет | ADR-0011 |
| MCP-M-1…MCP-M-7 | Read-only MCP master | отложено | DB-5 | ADR-0013 |
| ADR-0007 | Per-branch state | Proposed, Фаза 3 | classic multi-version | ADR-0007 |
| ADR-0010 | RW-agent production | Пауза | un-pause критерии | ADR-0010 |
| MS-8 | DefectDojo/ASOC экспорт | отложено | нет | ADR-0004 §8 |
| P1/P2 | Semantic dedup (эмбеддинги) | план | нет | ADR-0001 §11 |

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

## Прочие направления

- AG-6/AG-9 относятся к отдельному `appsecgate-agent` и не заменяют MM-3.
- Semantic dedup P1/P2, SonarQube, дашборды и MS-8 не блокируют TP-0001.
- E2E classic CI-полигон ведётся отдельно от TP-0001 (ADR-0003 §9).

## Ссылки на закрытые задачи

T1…T15, CI-1…CI-7, MS-1…MS-7 — `docs/history/phase-1-2-completed.md`.
