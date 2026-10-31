# Развёртывание master + edge (MS-7)

Центральный (master) сервер — единый источник правды для находок со всех
машин и CI (ADR-0004). Edge — синхронизация локальных БД разработчика
с master (`appsecgate-mcp sync`). Оба сервиса поднимаются корневым
`docker-compose.yml` **с включённой сетью** (решение владельца 2026-10-31);
`network_mode: none` остаётся только у STDIO MCP-сервера
(`mcp-server/docker-compose.yml`) для офлайн-вайб-кодеров.

## 1. Переменные окружения

Скопируйте пример и заполните ключи:

```bash
cp .env.example .env
```

| Переменная | Обязательна | Описание |
|---|---|---|
| `APPSECGATE_MASTER_API_KEYS` | да | JSON `{"project-id": "key"}` — карта проектов master |
| `APPSECGATE_MASTER_API_KEY` | да | Ключ edge для одного проекта (совпадает с ключом выше) |
| `APPSECGATE_PROJECT_ID` | да | ID проекта на master |
| `APPSECGATE_DATA_DIR` | нет | Каталог локальных БД edge на хосте (default `~/.appsecgate-mcp`) |

Генерация ключа: `openssl rand -hex 32`. Ключи уникальны на проект
(проверяется `MasterSettings`).

## 2. Сборка образов

```bash
make docker-master-build   # moondoom/appsecgate-master:0.1.0
make docker-build          # moondoom/appsecgate-mcp:0.1.0 (уже собран — Фаза 1)
```

## 3. Запуск master

```bash
make compose-up            # docker compose up -d master
```

- REST API: `http://127.0.0.1:8000` (порт проброшен только на loopback).
- Swagger: `http://127.0.0.1:8000/docs`, контракт: `/openapi.json`.
- Healthcheck: `GET /healthz` (compose ждёт его перед запуском edge).
- SQLite хранится в named volume `master-data` (`/home/appsecgate/.appsecgate/master/master.db`, WAL).

Проверка:

```bash
curl http://127.0.0.1:8000/healthz
curl -H "Authorization: Bearer $KEY" "http://127.0.0.1:8000/v1/findings?project=my-project"
curl -H "Authorization: Bearer $KEY" "http://127.0.0.1:8000/v1/findings?project=my-project&branch=main&commit=abc123"
```

`branch` и `commit` необязательны и фильтруют актуальный агрегат по
`last_seen_branch` / `last_seen_commit`; их можно сочетать с `state`.

## 4. Edge-синхронизация

Edge — контейнер образа MCP-сервера с командой `sync` (не STDIO). Он читает
`shown_findings.db` из `$APPSECGATE_DATA_DIR` на хосте, экспортирует события,
пушит их в master (outbox + идемпотентность) и тянет вниз suppressions/политики
(MS-3/MS-5). Outbox пишется в `sync/outbox.ndjson` внутри того же data-dir
(корневая ФС контейнера read_only).

```bash
make compose-edge-sync                 # docker compose run --rm edge
docker compose run --rm edge sync --dry-run    # только просмотр событий
docker compose run --rm edge sync --dry-run --format ndjson
```

Периодичность — на усмотрение команды: руками, cron или расписание CI.
Для «живой» синхронизации с машины разработчика можно также запускать
`appsecgate-mcp sync` на хосте (ADR-0004 §4.2, вариант А).

## 5. CI (appsecgate ci)

CI-шаг (GitHub Actions) всегда тянет «показанное» с master, без master —
exit 2 (fail-closed, MS-6). Рабочий пример:
`.github/workflows/appsecgate-ci.yml`. В репозитории потребителя задайте
секреты `APPSECGATE_MASTER_URL` и `APPSECGATE_MASTER_API_KEY`
(для этого проекта — соответствующий ключ из `APPSECGATE_MASTER_API_KEYS`).

## 6. Локальный запуск без Docker (для разработки master)

```bash
cd appsecgate-master && uv sync --extra dev
APPSECGATE_MASTER_API_KEYS='{"my-project":"dev-key"}' \
  uv run uvicorn appsecgate_master.api.app:create_app --factory \
  --host 127.0.0.1 --port 8000
```

`APPSECGATE_MASTER_DB` опционален (default `~/.appsecgate/master/master.db`).

## 7. Безопасность

- API-ключи — только через env/секреты; `MasterSettings` валидирует
  непустоту и уникальность.
- Redaction секретов на приёме (инвариант №4, ADR-0004 §5.4), аудит append-only.
- Порт `8000` в compose проброшен на `127.0.0.1`; для доступа извне —
  TLS reverse-proxy (nginx/caddy) и HTTPS-ключи.
- Образ master: non-root `1000:1000`, read_only rootfs, cap_drop ALL.

## 8. Troubleshooting

| Симптом | Причина | Действие |
|---|---|---|
| `compose up` требует `APPSECGATE_MASTER_API_KEYS` | Нет `.env` | `cp .env.example .env`, заполнить ключи |
| edge: `project mismatch` | Неверный `APPSECGATE_PROJECT_ID` / ключ | Проверить `.env` и `APPSECGATE_MASTER_API_KEYS` |
| edge: `HTTP 401` | Ключ не совпадает с картой master | Ключ edge = ключ проекта из `APPSECGATE_MASTER_API_KEYS` |
| edge: `shown_findings.db not found` | Пуст `APPSECGATE_DATA_DIR` | Указать каталог локальных БД (`~/.appsecgate-mcp`) |
| master не стартует | Ключ дублируется/пустой | `APPSECGATE_MASTER_API_KEYS` — уникальные непустые ключи |
