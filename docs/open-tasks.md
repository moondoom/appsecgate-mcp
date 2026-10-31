# Открытые задачи

> Активные пункты на 2026-10-31. Закрытые задачи — `docs/history/phase-1-2-completed.md`,
> детали реализации — `docs/history/implementation-notes.md`.
> Дизайн-решения — `docs/adr/`.

## Сводка

| # | Пункт | Тип | Блокер | Где детали |
|---|---|---|---|---|
| MS-8 | DefectDojo/ASOC экспорт | отложено | нет | ADR-0004 §8 |
| — | E2E CI-полигон (фиктивный PR) | этап Фазы 2 | нет | ADR-0003 §9 |
| ADR-0007 | Per-branch state | Proposed | блокирует classic | `adr/ADR-0007-*.md` |
| ADR-0008 | Orchestrator presets | Proposed | **блокер Фазы 2** | `adr/ADR-0008-*.md` |
| ADR-0009 | Агенты (dev/server/CI), `check_gate`, branch/commit в API | не создан | блокирует agent mode | тезисы C4–C9 |
| P1/P2 | Semantic dedup (эмбеддинги) | план | нет | ADR-0001 §11 |
| — | SonarQube, боевое слаживание, дашборды | направления статьи | нет | статья §«И что дальше» |

## Детали

### MS-8 — DefectDojo/ASOC
Отложено 2026-10-31, вне плана. Вернуть при актуализации vision (§5.2.4).

### E2E CI-полигон
По мотивам T14: фиктивный PR-дифф → проверка блокировки/пропуска `appsecgate ci`.
См. ADR-0003 §9.

### ADR-0007 — Per-branch state
Proposed, заглушка. Требует доработки (см. ревью): альтернативы, модель данных,
влияние на гейт-матрицу ADR-0006 §2.3, snapshot/master. Блокирует classic
multi-version (Фаза 3).

### ADR-0008 — Orchestrator presets
Proposed, **блокер Фазы 2**. Требует: таблица пресетов (5 осей × 3), удаление
`snapshot` из `shown-source` (удалён MS-6), явная судьба `escalate` (master
Paused) и `fix`/`rw` (внешний orchestrator, ADR-0010), маппинг policy →
GateDecision, конфиг-схема, критерии приёмки.

### ADR-0009 — Агенты
Не создан. Зафиксировать: три типа агентов (dev/server/CI), MCP-тул `check_gate`,
`GET /v1/findings?branch=&commit=` как контракт «актуальная версия»,
policy enforcement (AGENTS.md + `recommended_action` + action log), server-agent
`appsecgate-agent` (MVP = report mode без LLM), RW-агент — пауза (ADR-0010).

### Semantic dedup P1/P2 (ADR-0001)
P0 выполнен (tie-break, T10). P1/P2 (эмбеддинги, `finding_embeddings`, σ по
категориям) — не начаты, за фича-флагом `dedup.semantic.enabled`.

### Направления статьи
SonarQube-интеграция, боевое слаживание (50–100 проектов), дашборды (Фаза 4) —
не начаты.

## Ссылки на закрытые задачи

T1, T2, T3, T4, T5, T6, T7, T8, T9, T10, T11, T12, T13, T14, T15 —
`docs/history/phase-1-2-completed.md`.
CI-1..CI-7, MS-1..MS-7 — там же.
