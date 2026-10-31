# appsecgate-master

Центральный (master) сервер AppSecGate — единый источник правды для воронки
находок из всех репозиториев (Фаза 2, ADR-0004, ADR-0006).

> Статус: этап MS-4 — события/агрегат/аудит и REST API реализованы.
> Edge pull, CI-источник и Docker-деплой — последующие этапы (MS-5+).

## Область ответственности (ADR-0004 §2)

- Приём событий от edge-серверов (`push`), идемпотентный по `client_event_id`.
- Event-sourcing: события immutable, состояние пересчитывается (ADR-0006 §3.4).
- Единый агрегат `(project_key, fp)` с конфликт-резолюцией ADR-0006 §3.4.
- Append-only `audit_log` для всех переходов состояния.
- Redaction секретов до записи в БД (инвариант №4).
- Без LLM-вызовов и сетевого сканирования (инварианты №2/№3).

## Запуск API

```sh
export APPSECGATE_MASTER_API_KEYS='{"my-project":"replace-with-a-long-random-key"}'
export APPSECGATE_MASTER_DB="$HOME/.appsecgate/master/master.db"
cd appsecgate-master
uv run uvicorn appsecgate_master.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

`APPSECGATE_MASTER_API_KEYS` — обязательный JSON-объект `{project_key: api_key}`.
Ключи должны быть непустыми и уникальными. По умолчанию БД находится в
`~/.appsecgate/master/master.db`. OpenAPI доступен на `/openapi.json`, Swagger UI —
на `/docs`. TLS и rate-limit настраиваются на reverse-proxy согласно ADR-0004.

| Метод | Путь | Назначение |
|---|---|---|
| `POST` | `/v1/events` | Батч `{"events": [...]}`; ответ содержит per-event outcomes |
| `GET` | `/v1/findings?project=&state=` | Материализованные состояния находок |
| `GET` | `/v1/suppressions?project=` | Активные CI/global suppressions |
| `GET` | `/v1/config?project=` | Последняя `config_policy` или `policy: null` |
| `GET` | `/v1/audit?project=&since=&limit=` | Append-only аудит приёма |
| `GET` | `/healthz` | Liveness без аутентификации |

Все `/v1/*` требуют `Authorization: Bearer <api-key>` и проверяют соответствие
ключа проекту. Коды: 200 — accepted/duplicate; 400 — хотя бы одно событие отклонено
(`rejected:*` в outcomes); 401 — нет/неверен ключ; 403 — ключ чужого проекта;
422 — ошибка схемы или query-параметра. При 400 валидные события батча уже приняты:
edge повторяет их идемпотентно при single-event fallback, а отклонённые карантинит.

## Структура

```
src/appsecgate_master/
├── api/                  # FastAPI factory, auth, routes, response contracts
├── contracts/events.py   # MasterEvent: контракты событий (§1.4 + config_policy)
├── aggregate/            # state.py, matrix.py (§2.1), fold.py (§3.4)
├── security/redact.py    # redaction на приёме
└── storage/              # db.py, migrations, stores/{events,audit,aggregates}.py
```

## Разработка

```sh
make master-setup    # uv sync (FastAPI, uvicorn, pydantic + dev)
make master-check    # ruff + pytest
```

Схема БД создаётся с нуля (продукт не релизился, миграций нет). Версия схемы —
`schema_meta.schema_version`; при несовпадении таблицы пересоздаются
(паттерн ADR-0005 §2.7).
