# Детали реализации Фазы 2 (MS-2, MS-3, MS-5)

> Исторический документ. Сводка — в `docs/open-tasks.md`, дизайн — в ADR-0004/0006.
> Перенесено дословно из старого `docs/open-tasks.md` (этих деталей в ADR нет).

## MS-2 — схема master-БД (2026-10-31)

Создан пакет `appsecgate-master/` (Python ≥ 3.12,
зависимость — только pydantic; FastAPI — MS-4). Реализовано по ADR-0006
(заменяет ADR-0004 §5.3):

- `contracts/events.py` — `MasterEvent` (10 событий §1.4 + `config_policy`),
  алиасы полей snapshot-формата §3.3 (`event`/`project_id`), валидация UTC;
- `aggregate/` — `matrix.py` (таблица §2.1 + правила 2/3 §3.4), `fold.py`
  (LWW `(at, event_id|client_event_id)` + правила 1–6), `state.py`;
- `storage/` — SQLite WAL: `events` (append-only, дедуп по `client_event_id`),
  `audit_log` (append-only, триггеры против UPDATE/DELETE),
  `aggregates` (материализованный кэш, `rebuild()` из events);
  schema_version v1, drop-on-mismatch (ADR-0005 §2.7);
- `security/redact.py` — redaction на приёме (§5.4): секрет в `note`/`reason`
  → `rejected:redaction`, в БД не попадает;
- тесты: 114 (матрица, правила 1–6, ingest/дедуп/redaction, аудит, паритет
  snapshot-replay §3.3 ↔ master-агрегат);
- `make check` теперь валидирует оба пакета (mcp-server + appsecgate-master).

## MS-3 — edge sync (2026-10-31)

Edge-подкоманда `appsecgate-mcp sync` (ADR-0004 §4.2,
запускается НА ХОСТЕ вне контейнера — инвариант №2 не затрагивается).
Реализовано в `mcp-server/src/appsecgate_mcp/sync/` (только stdlib, G7):

- `export.py` — читает локальную `shown_findings.db` (только SELECT) и
  **реконструирует** события из materialized state (ADR-0006 §1.6: event-log
  локально не ведётся). Критерий: fold на master (§3.4) сворачивается в тот же
  статус. `client_event_id = uuid5(project, fp, event_type, at)` — стабилен
  между запусками и машинами → идемпотентный приём (дедуп §5.1);
- маппинг статус → события: SHOWN→discovered(+reaffirmed),
  POTENTIALLY_FIXED→+not_found_in_scope, FIXED→+not_found_in_scope
  (fixed_at−1µs, чтобы сложиться раньше verify) + verify_fixed,
  REOPENED→(fixed_at есть) +verify_fixed+reopened / (нет) +verify_not_fixed
  (аппроксимация — пути SHOWN→REOPENED в матрице §2.1 нет; оба статуса
  блокируют CI), SUPPRESSED→+suppressed (scope/expires из suppressions),
  WONT_FIX→+verify_wont_fix (note обязателен);
- `outbox.py` — durable NDJSON-очередь `~/.appsecgate/sync/outbox.ndjson`
  (§4.2): атомарные записи, дедуп по `client_event_id`, карантин битых
  (`*.corrupt`) и отвергнутых (`*.rejected`) строк;
- `push.py` — stdlib urllib, POST `{master}/v1/events` батчами + fallback
  по одному при 4xx; 2xx→удаление из очереди, 4xx→карантин, 5xx/сеть→retry;
- CLI: `appsecgate-mcp sync [--data-dir --project-id --outbox --master-url
  --api-key --batch-size --dry-run --format]`; exit 0/1/2 (как `ci`);
- тесты: 37 новых (маппинг каждого статуса, стабильность id, контракт полей,
  outbox roundtrip/карантин, push на реальном loopback-стабе, CLI e2e).

## MS-5 — pull вниз (2026-10-31)

Обычный `appsecgate-mcp sync` после push скачивает
CI/global suppressions и центральную policy для одного проекта:

- `pull.py` — stdlib urllib GET `/v1/suppressions` + `/v1/config`; оба ответа
  валидируются до записи, при ошибке сохраняется последняя скачанная копия;
- `remote_suppressions` — отдельная таблица в `shown_findings.db`; атомарная
  замена только текущего проекта, local-записи и export MS-3 не затрагиваются;
  скан применяет local + remote фильтры уже на следующем запуске;
- `master-policies/<project_id>.json` в data-dir; разрешены только `gates` и
  `rules`, приоритет `default < project < master < env`; применение — в новой
  MCP-сессии, без записи в `:ro`-проект и без HTTP на MCP-сервере;
- общий outbox фильтруется по `project_id`; multi-project БД требует явный
  `--project-id`; pull-ошибка → exit 1, dry-run остаётся локальным;
- 26 новых тестов: store/rollback, policy precedence, pull HTTP/CLI и
  project-scoped outbox на реальном loopback urllib.
