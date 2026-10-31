# Открытые задачи

> Активные пункты на 2026-10-31. Закрытые задачи — `docs/history/phase-1-2-completed.md`,
> детали реализации — `docs/history/implementation-notes.md`.
> Дизайн-решения — `docs/adr/`.

## Фактическое состояние

- Фаза 1 и технические этапы CI-1…CI-7, MS-1…MS-7 завершены.
- В MCP зарегистрировано 15 тулов; `check_gate` реализован (OR-1).
- `GET /v1/findings` поддерживает фильтры `state`, `branch` и `commit` (OR-2).
- `make check`: 496 тестов mcp-server + 143 теста appsecgate-master — зелёные.
- ADR-0007…ADR-0009 содержат проектные решения, но не означают реализацию.

## Сводка

| # | Пункт | Статус | Блокер | Где детали |
|---|---|---|---|---|
| OR-1 | MCP-тул `check_gate` | выполнен | — | ADR-0008 §4, ADR-0009 §3 |
| OR-2 | `GET /v1/findings?branch=&commit=` | выполнен | — | ADR-0008 §5 |
| OR-5 | Документация двух режимов оркестрации | выполнена | — | ADR-0008 §9 |
| OR-6 | Примеры classic PR/release/cron | выполнены | — | ADR-0008 §9 |
| AG-3 | Шаблон AppSecGate policy для AGENTS.md | выполнен | — | ADR-0009 §4 |
| OR-7/AG-4 | Пример CI-agent | выполнен | — | ADR-0008 §9, ADR-0009 §13 |
| AG-5/AG-8 | Server-agent MVP: report + workflow | не начат | OR-1, OR-2 | ADR-0009 §13 |
| AG-6/AG-9 | Triage, action log и audit push | после MVP | AG-5 | ADR-0009 §13 |
| — | E2E CI-полигон (фиктивный PR) | не начат | нет | ADR-0003 §9 |
| ADR-0007 | Per-branch state | Proposed, Фаза 3 | classic multi-version | `adr/ADR-0007-*.md` |
| ADR-0010 | RW-agent | Пауза, ADR не создан | RW/fix mode | ADR-0009 §7 |
| MS-8 | DefectDojo/ASOC экспорт | отложено | нет | ADR-0004 §8 |
| P1/P2 | Semantic dedup (эмбеддинги) | план | нет | ADR-0001 §11 |
| — | SonarQube, боевое слаживание, дашборды | направления | нет | product vision |

## Детали

### OR-1 / OR-2 — блокеры agent mode
Оба выполнены: `check_gate` возвращает `GateSummary` и `recommended_action`
по последнему скану выбранного scope; master API принимает опциональные
`branch`/`commit` без изменения поведения запросов без этих параметров.
AG-1/AG-2 из ADR-0009 — те же задачи, отдельно не ведутся.

### OR-3 / OR-4 — закрыты документацией
ADR-0003 переведён в classic hard-gate; snapshot-разделы помечены историческими.
ADR-0006 разделяет advisory agent mode и enforced classic gate.

### OR-5 / OR-6 — документация и примеры
Выполнено: `docs/deploy-agents.md` описывает выбор agent mode vs classic
hard-gate; PR/release/cron покрыты отдельными workflow. Шаблон AG-3 находится
в `mcp-server/examples/AGENTS.md`.

### ADR-0007 — Per-branch state
Proposed, Фаза 3. Модель `(project, branch, fingerprint)` описана; реализация
PB-1…PB-6 не начата. До неё classic multi-version остаётся ограничением Фазы 2.

### ADR-0009 — модель агентов
ADR создан и имеет статус Proposed. Реализация ведётся через OR-1/OR-2 и
AG-3…AG-9; server-agent и CI-agent в репозитории пока отсутствуют.

### MS-8 — DefectDojo/ASOC
Отложено 2026-10-31, вне плана. Вернуть при актуализации vision (§5.2.4).

### E2E CI-полигон
По мотивам T14: фиктивный PR-дифф → проверка блокировки/пропуска `appsecgate ci`.
См. ADR-0003 §9.

### Semantic dedup P1/P2 (ADR-0001)
P0 выполнен (tie-break, T10). P1/P2 (эмбеддинги, `finding_embeddings`, σ по
категориям) — не начаты, за фича-флагом `dedup.semantic.enabled`.

### Направления статьи
SonarQube-интеграция, боевое слаживание (50–100 проектов), дашборды (Фаза 4) —
не начаты.

## Ссылки на закрытые задачи

T1…T15, CI-1…CI-7, MS-1…MS-7 — `docs/history/phase-1-2-completed.md`.
