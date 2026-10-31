# appsecgate-master

Центральный (master) сервер AppSecGate — единый источник правды для воронки
находок из всех репозиториев (Фаза 2, ADR-0004, ADR-0006).

> Статус: этап MS-2 — схема БД, события/агрегат/аудит, unit-тесты.
> HTTP-API, git-вебхуки и деплой — последующие этапы (MS-4+).

## Область ответственности (ADR-0004 §2)

- Приём событий от edge-серверов (`push`), идемпотентный по `client_event_id`.
- Event-sourcing: события immutable, состояние пересчитывается (ADR-0006 §3.4).
- Единый агрегат `(project_key, fp)` с конфликт-резолюцией ADR-0006 §3.4.
- Append-only `audit_log` для всех переходов состояния.
- Redaction секретов до записи в БД (инвариант №4).
- Без LLM-вызовов и сетевого сканирования (инварианты №2/№3).

## Структура

```
src/appsecgate_master/
├── contracts/events.py   # MasterEvent: контракты событий (§1.4 + config_policy)
├── aggregate/            # state.py, matrix.py (§2.1), fold.py (§3.4)
├── security/redact.py    # redaction на приёме
└── storage/              # db.py, migrations, stores/{events,audit,aggregates}.py
```

## Разработка

```sh
make master-setup    # uv sync (pydantic + dev)
make master-check    # ruff + pytest
```

Схема БД создаётся с нуля (продукт не релизился, миграций нет). Версия схемы —
`schema_meta.schema_version`; при несовпадении таблицы пересоздаются
(паттерн ADR-0005 §2.7).
