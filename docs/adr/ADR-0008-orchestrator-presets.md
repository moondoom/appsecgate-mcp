# ADR-0008: Orchestrator presets

**Статус:** Proposed
**Дата:** 2026-10-31
**Файл:** `docs/adr/ADR-0008-orchestrator-presets.md`
**Блокирует:** **Блокер приёмки Фазы 2**.
**Контекст:** заглушка — решения фиксируются до приёмки Фазы 2 (PR-D/SM-2).
**Связанные:** ADR-0003 (CI), ADR-0006 (lifecycle), ADR-0007 (per-branch state)

---

## 1. Контекст

Три архетипа использования: solo-разработчик, agent-wrangler (агент гоняет сканы
и фиксы), classic (CI-шлюз на ветках/PR). Один набор дефолтов конфигурации
не подходит всем трём.

## 2. Ось конфигурации

`trigger × scope × policy × write × shown-source`:

- `trigger` — manual / on-save / pre-commit / CI;
- `scope` — file / diff / project;
- `policy` ∈ {`warn`, `block`, `escalate`, `fix`};
- `write` ∈ {`ro`, `rw`};
- `shown-source` — local / snapshot / master.

## 3. Пресеты

`solo` / `agent-wrangler` / `classic` — готовые комбинации оси §2; переопределение
отдельных осей — через конфиг (ADR-0006 §1.7).

## 4. `policy` ∈ {warn, block, escalate, fix}

Уровни реакции: `warn` (не блокирует), `block` (exit ≠ 0), `escalate`
(только с master-сервером, ADR-0004), `fix` (оркестрация автофикса агентом).

## 5. `write` ∈ {ro, rw}

`ro` — инвариант №1 (сервер не пишет файлы проекта); `rw` — только
внешний orchestrator-контур, не `mcp-server`.

## 6. cron / release

Периодические прогоны (cron) и релизный гейт (release) — точки подключения
пресетов к CI-контуру.

## 7. Влияние

На ADR-0003 (§5.2, §6 snapshot), ADR-0006 (§2.3 гейт-матрица), схему `Config`
(новые секции/пресеты), `gate.py`/`ci.py`.

## 8. Не-цели

RBAC, роли людей, ГОСТ-отчёты (product-vision Фазы 3–5) — вне этого ADR.