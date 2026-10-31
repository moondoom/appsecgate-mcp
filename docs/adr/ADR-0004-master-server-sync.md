# ADR-0004: Центральный (master) сервер — дизайн, стек, синхронизация

**Статус:** Paused (superseded in parts by ADR-0006)
**Дата:** 2026-10-30
**Контекст:** Фаза 2, этап 2 — центральный сервер как единый источник правды
**Решает:** как синхронизировать находки/показанное/подтверждения между машинами
и CI без нарушения инварианта №2 (сервер без сети)

---

## 1. Контекст

- Product vision `docs/product-vision.md` §5.2: master-сервер — «КОНТУР 2»,
  единый источник правды: централизованная конфигурация, синхронизация
  находок со всех машин и CI, suppression-синхронизация вниз (§4.6:
  CI/global suppression скрывает находку в IDE), аудит, SLA-таймеры,
  интеграция с ASOC/DefectDojo.
- Уже реализовано (Фаза 1 + этап CI, ADR-0003):
  - три локальные SQLite-БД на volume машины разработчика: findings,
    `shown_findings.db` (журнал показанного, retention 30 дней),
    suppressions/feedback;
  - `fingerprint` — детерминированный ключ сопоставления находок между
    машинами и сканами (ADR-0001);
  - `verify_fix` пишет `fix_attempts` → `verified_status: fixed|not_fixed|wont_fix`;
  - suppression `scope: local|ci|global` (сейчас `local` фильтрует только локально);
  - CI-этап (ADR-0003): `appsecgate ci` читает «показанное» из опционального
    snapshot `.appsecgate-mcp/shown.ndjson` (пишет агент) — **промежуточный
    мостик** до master: с появлением master-сервера CI сможет тянуть
    показанное с сервера, snapshot остаётся офлайн-fallback.
- Открытый вопрос `docs/architecture.md` §9.5: «Синхронизация shown_findings
  с master: как разрешать конфликты, если один и тот же fingerprint показан
  на разных машинах?» — решается в §5.3.
- Ограничения (AGENTS.md, инварианты):
  - **№1** проект монтируется `:ro` — сервер НЕ пишет файлы проекта;
  - **№2** `network_mode: none` — **никаких HTTP-вызовов** на MCP-сервере.
    «Ни в Фазе 1, ни „на будущее"»;
  - **№4** redaction секретов до записи в БД;
  - **№5** `query_findings_db` — только SELECT по публичным views;
  - новые production-зависимости запрещены **без явного указания** (нужно
    зафиксировать в этом ADR);
  - `appsecgate-mcp ci` в CI-контейнере тоже запускается `:ro` + `network none`.

## 2. Цели и не-цели

### Цели

| # | Цель | Метрика |
|---|------|---------|
| G1 | Единый источник правды: находки + показанное + verified + suppressions со всех машин и CI | мастер хранит события из всех источников, дедуп по fingerprint |
| G2 | CI может получать «показанное» с master (замена snapshot как основного канала) | `appsecgate ci --shown-source master` |
| G3 | Suppression CI/global синхронизируются **вниз** на машины разработчиков (§4.6) | edge применяет pull-политики |
| G4 | Конфликт §9.5 разрешён детерминированно | таблица приоритетов §5.3 |
| G5 | Инвариант №2 не нарушен: MCP-сервер остаётся без сети | network none в docker-compose; сеть только у edge-процесса на хосте |
| G6 | Redaction при приёме (инвариант №4) | приём только данных из публичных views/снапшотов |
| G7 | mcp-server не получает новых production-зависимостей | pyproject mcp-server без изменений |

### Не-цели

- Web UI, WebSocket real-time, SLA-таймеры/автоэскалация — отдельные этапы.
- RBAC/роли (Фаза 3), ГОСТ-модуль — вне этого этапа.
- Интеграция с ASOC/DefectDojo — отдельный этап MS-8.
- Master **не сканирует** код — только хранит/агрегирует/отдаёт события.
- Не менять сигнатуры существующих MCP-тулов.

## 3. Кандидаты — кто делает сеть

Проблема: инвариант №2 запрещает HTTP из MCP-сервера. Синхронизацию должен
выполнять кто-то другой.

### Вариант А — edge-синхронизатор на хосте (рекомендуется)

Отдельный процесс **на машине разработчика, вне контейнера**
(`appsecgate-mcp sync`): читает локальные SQLite-БД (через те же
store-классы/публичные views), собирает события и пушит их на master по
HTTPS. Pull политик вниз — тот же процесс.

- ✅ Инвариант №2 цел: контейнер MCP-сервера без сети.
- ✅ Явное действие: синхронизация запускается пользователем/агентом/кроном.
- ✅ Возможен полный цикл: push вверх (находки, показанное, verified,
  suppressions) + pull вниз (политики, CI/global suppressions).
- ❌ Нужен HTTP-клиент на хосте (см. §4.2).

### Вариант Б — агент через MCP-тулы

Агент вызывает существующий `export_snapshot`, а транспорт до master
обеспечивает сам агент (его окружение имеет сеть).

- ✅ Ноль кода на хосте.
- ❌ Pull политик вниз невозможен без edge; агент — ненадёжный транспорт
  (нет аудита, нет очереди неотправленного); нет автоматизации.
- Место: **fallback** для ручной выгрузки, не основной канал.

### Вариант В — дать сеть MCP-серверу

Пересмотреть инвариант №2 для Фазы 2.

- ❌ Нарушает AGENTS.md «ни на будущее», меняет модель угроз контейнера
  (read-only + no-network — ключевой аргумент безопасности).
- Отклонён; повторное рассмотрение — только явным решением.

### Решение

**Q1: транспорт — Вариант А** (edge на хосте), Вариант Б — как ручной
fallback. Инвариант №2 не пересматривается.

## 4. Решение — стек

### 4.1. Master-сервер — отдельный компонент

Не расширять `mcp-server`: master — **новый пакет `appsecgate-master`** с
собственным `pyproject.toml` и Dockerfile (отдельный контейнер в
docker-compose). Это сохраняет изоляцию зависимостей и позволяет ставить
master только там, где он нужен (у команды, а не у каждого разработчика).

- Язык/рантайм: **Python 3.12** (общий с mcp-server), Pydantic v2 для
  контрактов — единый стек; общий код моделей событий выносится в
  нейтральный модуль (например `appsecgate_master/contracts`).
- Веб-фреймворк: **FastAPI** (ASGI; OpenAPI-схема = контракт) + **uvicorn**.
- Хранилище: **SQLite (WAL)** на первый этап (один контейнер, нулевой
  DevOps); **PostgreSQL** — опция для мультикомандного масштаба, выносится
  за storage-абстракцию (репозиторий/DAO), не зашивается.
- Аудит-лог: таблица событий append-only (§5.4).

> Это **явное указание** новых production-зависимостей для отдельного
> компонента; `mcp-server/pyproject.toml` не меняется (G7).

### 4.2. Edge-клиент на хосте

`appsecgate-mcp sync` — та же утилита, но запускается **на хосте вне
контейнера** (либо в отдельном контейнере с сетью), не в read-only/no-network
контейнере MCP-сервера.

- HTTP-клиент: **stdlib `urllib`** на первый этап — **ноль новых
  зависимостей**; если понадобятся таймауты/retry/pooling — отдельный
  ресёрч (httpx), решение фиксируется отдельным пунктом.
- Очередь неотправленного: локальный файл-журнал событий
  (`~/.appsecgate/sync/outbox.ndjson`), idempotent push
  (`client_event_id` — идемпотентность на мастере).

## 5. Модель данных, API, конфликт-резолюция

### 5.1. События (push вверх)

| Событие | Поля (redacted, инвариант №4) |
|---|---|
| `finding_shown` | `project_key`, `fp`, `rule_id`, `file`, `line`, `severity`, `shown_at`, `shown_by` |
| `finding_verified` | `project_key`, `fp`, `verified_status` (fixed/not_fixed/wont_fix), `attempted_at`, `note` |
| `suppression_created` | `project_key`, `fp`, `scope` (ci/global), `reason`, `expires_at`, `created_by`, `created_at` |
| `config_policy` | `project_key`, `gates.ci.*`, `gates.local.*`, `rules.*` (справочная синхронизация политик) |

Каждое событие несёт `client_event_id` (uuid) — идемпотентный приём.


### 5.2. REST API (контракт, OpenAPI)

| Метод | Путь | Кто | Назначение |
|---|---|---|---|
| `POST` | `/v1/events` | edge | push одного/батча событий; идемпотентность по `client_event_id` |
| `GET` | `/v1/findings?project=&state=` | CI/edge | агрегат находок проекта (текущее состояние по событиям) |
| `GET` | `/v1/suppressions?project=` | edge | pull CI/global suppressions **вниз** (G3) |
| `GET` | `/v1/config?project=` | edge | центральные политики (gates, thresholds) |
| `GET` | `/v1/audit?project=&since=` | AppSec/отчёты | аудит-лог (кто/когда/что) |
| `GET` | `/healthz` | инфра | liveness |

Аутентификация: `Authorization: Bearer <api-key>` (API-ключ на проект).
TLS-termination — на reverse-proxy (nginx/Caddy) вне контейнера master.
Rate-limit и размер тела — на том же прокси.

### 5.3. Конфликт-резолюция (решает §9.5)

> **Обновление 2026-10-31 (ADR-0006, MS-2):** этот раздел **замещён**
> [ADR-0006](ADR-0006-unified-finding-lifecycle-model.md) §3.4 (snapshot-based
> lifecycle + единый fold `(at, event_id)`). Мастер-агрегат `(project_key, fp)`
> реализован в пакете `appsecgate-master/` по ADR-0006: матрица §2.1 +
> правила 1–6 §3.4, дедуп по `client_event_id`, append-only `audit_log`,
> redaction на приёме (§5.4). Ниже — исходный текст для истории.

Ключ находки: `(project_key, fp)`. Состояние — **агрегат событий** (event
sourcing: события immutable, состояние пересчитывается). Конфликт — события
про один `fp` с разных машин. Детерминированное правило:

1. **Suppression перезаписывает всё** в пределах своего `scope`:
   `ci`/`global` suppression создан → находка в CI закрыта, а pull-политика
   синхронизируется вниз; `local` suppression на мастере не хранится как
   глобальная истина (остаётся на машине).
2. **`verified_status`** имеет приоритет над `shown` для того же `fp`:
   `fixed` > `wont_fix` > `not_fixed` > (был показан).
3. **Однотипные события**: Last-Write-Wins по `shown_at`/`attempted_at`/
   `created_at` (UTC, ISO-8601); при равенстве — меньший
   `client_event_id` (uuid) для детерминизма.
4. **`shown` с разных машин** — не конфликт: это множество «кто видел»;
   для `block_on_unresolved_local` достаточно существования хотя бы одного
   `shown`, не закрытого правилами 1–2.
5. Каждое событие пишется в аудит-лог; исходное решение о конфликте
   воспроизводимо пересчётом агрегата.

### 5.4. Аудит

Append-only таблица `audit_log` (все события + ключ/проект + timestamp).
Никаких `UPDATE`/`DELETE` — только insert. Redaction на приёме: значения
проверяются на соответствие публичным views/схеме snapshot ADR-0003
(признаки секретов в полях `note`/`reason` — отбрасываются).

## 6. CI-интеграция

`appsecgate ci` получает `--shown-source master|snapshot|local`:

- `master` (по умолчанию при наличии master): CI тянет «показанное» с
  `GET /v1/findings` (флаги shown/verified/suppressed) — snapshot не нужен;
- `snapshot`: текущее поведение ADR-0003 (офлайн/без master);
- отсутствие master и snapshot → warning + severity-gate (fail-open, как
  сейчас). `--require-shown-source` ужесточает.

## 7. Принятые решения (Q1–Q7)

| # | Вопрос | Решение |
|---|---|---|
| Q1 | Кто делает сеть | **Вариант А** — edge-процесс на хосте (`appsecgate-mcp sync`); MCP-сервер без сети (инвариант №2 не пересматривается); вариант Б (агент через тулы) — ручной fallback |
| Q2 | Master как отдельный компонент | Пакет `appsecgate-master` (FastAPI + uvicorn, Pydantic v2, SQLite WAL; Postgres — опция за DAO); `mcp-server/pyproject.toml` не меняется |
| Q3 | HTTP-клиент edge | stdlib `urllib` на первый этап (ноль новых зависимостей); httpx — только отдельным ресёрчем |
| Q4 | Конфликт §9.5 | Event sourcing: immutable события + агрегат; приоритеты: suppression(ci/global) > verified(fixed>wont_fix>not_fixed) > shown; LWW по UTC-таймстампу + детерминированный tie-break по `client_event_id` |
| Q5 | Pull политик вниз | Входит: edge периодически тянет `GET /v1/suppressions` + `GET /v1/config` (§4.6, G3) |
| Q6 | CI-источник показанного | `--shown-source master\|snapshot\|local`; master — основной канал при его наличии, snapshot — fallback (ADR-0003 сохраняется) |
| Q7 | Безопасность | Bearer API-ключ на проект, TLS на reverse-proxy, redaction при приёме, аудит append-only; лог без промптов и сырых секретов |



## 8. План внедрения

| Этап | Содержание | Репо |
|---|---|---|
| **MS-1** | Принятие ADR-0004 (этот документ), обновление `docs/adr/README.md`, `docs/architecture.md` §8/§9.5, `docs/open-tasks.md` | docs |
| **MS-2** | Схема master-БД + события/агрегаты + аудит; unit-тесты агрегата | appsecgate-master |
| **MS-3** | Edge `appsecgate-mcp sync`: экспорт из локальных БД в события, outbox, idempotent push (urllib) | mcp-server (edge-подкоманда, вне контейнера) |
| **MS-4** | Master REST API (FastAPI): `/v1/events`, `/v1/findings`, `/v1/suppressions`, `/v1/config`, `/v1/audit`, `/healthz`; OpenAPI-контракт | appsecgate-master |
| **MS-5** | Pull вниз: edge применяет CI/global suppressions и политики локально (скрытие в IDE, без записи в `:ro`-проект) | mcp-server / appsecgate-master |
| **MS-6** | CI-источник: `--shown-source master` в `appsecgate ci`; контрактные тесты; `make check` зелёный | mcp-server / appsecgate-master |
| **MS-7** | Docker Compose: master + edge, документация развёртывания, пример для команды | docs / docker |
| **MS-8** | DefectDojo/ASOC экспорт (vision §5.2.4) — отдельный этап после MS-7 | appsecgate-master |

## 9. Тестирование

- Unit: агрегат конфликт-резолюции §5.3 (каждое правило 1–5); идемпотентность
  `client_event_id`; redaction-проверка на приёме.
- Контрактные: OpenAPI-схема master против клиента edge (schema-driven).
- Интеграция: edge → master (localhost), push/pull в обе стороны.
- E2E (отдельный этап): две машины + CI пушат в один master → конфликт
  показанного §9.5 на реальном `fp`; `block_on_unresolved_local` через master.
- Регресс: `make check` (355 тестов) — mcp-server не меняется по G7.

## 10. Ссылки

- `docs/product-vision.md` §4.2–4.7, §5.2 (master, двойной контур, suppression)
- `docs/architecture.md` §8 (границы фаз), §9.5 (конфликт синхронизации)
- `docs/adr/ADR-0003-ci-unresolved-local-delivery.md` — snapshot как
  промежуточный канал; `docs/adr/ADR-0001-fingerprint-and-semantic-dedup.md` — fingerprint
- `orchestration/gate.py`, `storage/stores/*`, `server/ci.py`, `git.py`
