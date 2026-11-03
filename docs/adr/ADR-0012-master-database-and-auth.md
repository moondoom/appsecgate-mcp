# ADR-0012: СУБД master-сервера и фундамент авторизации

**Статус:** Accepted, реализовано (2026-11-02)
**Дата:** 2026-11-01
**Файл:** `docs/adr/ADR-0012-master-database-and-auth.md`
**Контекст:** Фаза 2, после MS-7. Master работает на SQLite WAL, что было достаточно для MVP, но не выдерживает требований мультикомандного развёртывания, RBAC и конкурентной идемпотентности. Одновременно — это момент, когда закладывается фундамент для Phase 3 (user RBAC), чтобы не ломать схему позже.
**Уточняет:** ADR-0004 §4.1 — PostgreSQL перестаёт быть «опцией за DAO» и становится основным production-backend для master; SQLite остаётся для локального/одиночного развёртывания.
**Делегирует:** MCP-интерфейс для master — в ADR-0013. Авторизация (модель, RLS, ключи, задел на Phase 3) — **здесь**.
**Связанные:** ADR-0004 (master server), ADR-0006 (lifecycle model, §3.4 master merge), ADR-0008 (orchestrator presets)

---

## 1. Контекст

### 1.1. Текущее состояние

Master реализован на SQLite WAL (ADR-0004 Q2). Это осознанное решение первого этапа: один контейнер, минимум эксплуатации, ноль DevOps. Оно хорошо работало для MVP и продолжает работать для локального/одиночного развёртывания.

Однако SQLite имеет архитектурные ограничения, которые становятся блокирующими при переходе к мультикомандному сценарию:

- **Один писатель.** Конкурентные `INSERT` из нескольких edge-процессов сериализуются через файловую блокировку, что приводит к `SQLITE_BUSY` и retry-костылям.
- **Нет сетевого доступа.** SQLite-файл нельзя безопасно открыть по сети; MCP для master (ADR-0013) требует сетевого протокола.
- **Нет RBAC.** Изоляция проектов возможна только на уровне приложения; в ядре БД нет ролей и политик.
- **Нет репликации и бэкапов «из коробки».** Для always-on CI-контура (fail-closed exit 2 при недоступности master) это риск.
- **Ограниченная аналитика.** Агрегации по большим объёмам событий деградируют; для Phase 4 (дашборды) потребуется отдельный контур.

### 1.2. Что уже зафиксировано

- ADR-0004 §4.1: PostgreSQL **разрешён и предусмотрен архитектурой** как «опция для мультикомандного масштаба, выносится за storage-абстракцию (репозиторий/DAO), не зашивается».
- ADR-0006 §3.4: master merge — event sourcing, дедупликация по `client_event_id`, append-only `audit_log`, агрегат per `(project, fp)`.
- Инвариант №2 (`network_mode: none`) относится к MCP-серверу сканера, не к master. Master уже работает в сети; подключение к PostgreSQL его не нарушает.

То есть переход на PostgreSQL — это **реализация уже запланированной опции**, а не смена архитектурного направления.

### 1.3. Триггер пересмотра и задел на Phase 3

MS-7 (Docker Compose master + edge) завершён. Следующий логичный шаг — подготовка к мультикомандному развёртыванию. Текущая реализация SQLite-специфична (placeholders `?`, `INSERT OR REPLACE`, `AUTOINCREMENT`, триггеры с `RAISE(ABORT)`, `sqlite_master`/`sqlite_sequence`), поэтому простая замена строки подключения невозможна — требуется выделенный ADR.

**Ключевое расширение этого ADR:** одновременно с выбором PostgreSQL выбирается **модель авторизации**, рассчитанная на Phase 3 (user RBAC), но в Phase 2 реализуется только API-key слой. Схема и RLS-политики проектируются так, чтобы при добавлении пользователей, ролей и OIDC **не менять таблицы и не переписывать политики** — только populate новые таблицы и включить новый auth-flow. Это позволяет избежать болезненной миграции схемы в Phase 3.

---

## 2. Цели и не-цели

### Цели

| # | Цель | Метрика |
|---|------|---------|
| G1 | Master выдерживает конкурентные push'и от нескольких edge-процессов | Нет `SQLITE_BUSY`-retry; дедупликация через уникальное ограничение БД |
| G2 | Транзакционная идемпотентность | `INSERT ... ON CONFLICT (client_event_id) DO NOTHING`; атомарность event + audit + aggregate |
| G3 | Append-only гарантии на уровне ядра | Триггеры + RBAC (запрет UPDATE/DELETE для роли приложения) |
| G4 | Изоляция проектов | RLS по `project_key`; роль приложения `NOSUPERUSER NOBYPASSRLS` |
| G5 | Сетевой протокол для будущего MCP master | PostgreSQL wire protocol (см. ADR-0013) |
| G6 | Сохранение SQLite для локального/одиночного развёртывания | Два backend'а за общим интерфейсом; SQLite — default |
| G7 | Внешние контракты не меняются | `POST /v1/events`, `GET /v1/findings`, `/v1/suppressions`, `/v1/config`, `/v1/audit`, `/healthz` — без изменений |
| G8 | Готовность к Phase 4 (аналитика) без преждевременной оптимизации | ClickHouse — отложен, с явными критериями перехода (§9) |
| **G9** | **Фундамент авторизации с заделом на Phase 3** | **Схема и RLS accommodate API-key (сейчас) и user RBAC (позже) без ALTER TABLE и переписывания политик** |

### Не-цели

- **Не** отказываться от SQLite. Он остаётся default для edge и одиночного master.
- **Не** внедрять ClickHouse на этом этапе. Он не нужен ни одной из текущих групп пользователей (§5) при текущих объёмах (§4).
- **Не** делать миграции существующих SQLite-данных. Продукт pre-release; чистый старт допустим (см. §6.7).
- **Не** менять `mcp-server/pyproject.toml`. Новая зависимость — только в `appsecgate-master`.
- **Не** реализовывать user RBAC в Phase 2. Только схема и RLS-фундамент; UI, OIDC, управление пользователями — Phase 3.
- **Не** вводить управление пользователями через API в Phase 2 — только service-to-service API-key.

---

## 3. Анализ конкурентов (ASOC/ASPM)

Рынок ASOC/ASPM демонстрирует устойчивый паттерн: **разделение OLTP и OLAP-нагрузки**.

| Продукт | Основная БД | Аналитический контур | Комментарий |
|---|---|---|---|
| **TRON.ASOC** (РФ) | PostgreSQL | ClickHouse | Issues и события их изменения — в ClickHouse; сущности системы — в PostgreSQL |
| **DefectDojo** (OWASP) | PostgreSQL | — | Django + PostgreSQL + Redis/Celery; production — внешняя managed PostgreSQL |
| **Snyk / SonarQube** | Собственная OLTP | ClickHouse (экспорт) | Аналитика и дашборды — в ClickHouse; транзакционные данные — отдельно |

**Вывод:** конкуренты не выбирают «или PostgreSQL, или ClickHouse». Они используют **PostgreSQL как system of record** для сущностей, требующих транзакционной целостности, и **ClickHouse как систему анализа** для высокообъёмных append-only потоков.

Этот ADR следует тому же паттерну: PostgreSQL — сейчас, ClickHouse — когда объёмы и потребности Phase 4 это оправдают (§9).

---

## 4. Профиль нагрузки

### 4.1. Заявленный сценарий

- **100 репозиториев**
- **1000 сканирований в день**
- Несколько edge-процессов на команду (10–30 машин)

### 4.2. Расчёт

| Параметр | Значение | Комментарий |
|---|---|---|
| Событий на сканирование (среднее) | 100–200 | `discovered`, `reaffirmed`, `not_found_in_scope`, `verify_*` |
| Событий в день | **100 000–200 000** | 1000 × 100–200 |
| Средняя пропускная способность | **~1.2–2.3 события/сек** | 24 часа |
| Пиковая нагрузка (10–20× от средней) | **~12–46 событий/сек** | Утренние CI-волны, релизы |
| Объём event-log за год (1 КБ/событие) | **36–73 ГБ** | Без индексов |
| Объём audit_log за год | **~равен event-log** | 1:1 с событиями |
| Агрегаты `(project, fp)` | **~100 000 строк** | 100 репо × 1000 находок — стабильный, малый |
| Итого с индексами | **~100–150 ГБ/год** | Легко управляется PostgreSQL |

### 4.3. Вывод

**Это умеренная OLTP-нагрузка.** PostgreSQL с правильными индексами и партиционированием по времени (monthly partitions для `events` и `audit_log`) обрабатывает десятки тысяч вставок в секунду. Заявленный профиль — на порядки ниже возможностей PostgreSQL.

ClickHouse на этих объёмах был бы **преждевременной оптимизацией**: добавил бы операционную сложность (MergeTree, TTL, отдельный бэкап, отдельный мониторинг) без ощутимой выгоды. Порог для ClickHouse — см. §9.

---

## 5. Группы пользователей и их потребности

Выделены на основе анализа продукта и статьи автора. Каждая группа предъявляет разные требования к хранилищу master.

### 5.1. SOLO-VIBE-CODER'ы

- **Потребности:** минимум настройки, локальность, быстрый старт, низкая цена.
- **Master:** не нужен. Работают с edge + SQLite.
- **Вывод:** SQLite остаётся default. Если бы ADR выбрал «только PostgreSQL», это отрезало бы сегмент.

### 5.2. Корпоративный заказчик (средний сегмент)

- **Потребности:** on-prem, публичные LLM запрещены, compliance, аудит, интеграция с корпоративным стеком (SonarQube), RBAC.
- **Master:** нужен, on-prem, с гарантиями аудита.
- **Почему PostgreSQL:** транзакционная целостность для аудита, RLS для изоляции, знакомый DevOps-стек, managed-варианты (Patroni, CloudNativePG).
- **Почему не ClickHouse:** нужен OLTP, а не OLAP. ClickHouse не даёт полноценных ACID и уникальных ограничений.

### 5.3. Операторы мультиагентных систем

- **Потребности:** API-first, автономность, агрегация событий от многих агентов, надёжность, конкурентность, идемпотентность.
- **Master:** критически важен, работает как сервис под нагрузкой.
- **Почему PostgreSQL:** MVCC, `INSERT ... ON CONFLICT`, сетевой протокол, репликация. SQLite с одним писателем здесь архитектурно не подходит.
- **Почему не ClickHouse:** агенты пушат события конкурентно; дедупликация по `client_event_id` требует уникального ограничения — в ClickHouse это эмуляция через приложение, что хрупко.

### 5.4. Классические команды разработки

- **Потребности:** CI fail-closed (exit 2 при недоступности master), always-on, транзакции, воспроизводимость.
- **Master:** единственный источник истины для CI (ADR-0006 §3.5).
- **Почему PostgreSQL:** репликация, бэкапы, атомарность event + audit + aggregate, детерминизм.

### 5.5. Phase 3 — user RBAC (будущая группа)

- **Потребности:** роли, OIDC, членство в проектах, аудит действий пользователей.
- **Master:** должен поддерживать user-level auth без ломки схемы.
- **Почему PostgreSQL с RLS:** RLS — единственный механизм, который позволяет перейти от API-key к user RBAC без переписывания политик изоляции (§6.9).

### 5.6. Сводная таблица

| Группа | SQLite | PostgreSQL | ClickHouse | Вердикт |
|---|---|---|---|---|
| Solo-vibe-coder | ✅ | ❌ избыточен | ❌ | SQLite default |
| Корпоративный заказчик | ❌ | ✅ | ❌ | PostgreSQL |
| Мультиагентные операторы | ❌ | ✅ | ❌ | PostgreSQL |
| Классические команды | ❌ | ✅ | ❌ | PostgreSQL |
| Phase 3 (user RBAC) | ❌ | ✅ | ❌ | PostgreSQL + RLS (§6.9) |
| Phase 4 (аналитика) | ❌ | ⚠️ возможно | ✅ | ClickHouse — отложен (§9) |

---

## 6. Решение

### 6.1. Основной backend — PostgreSQL 16+

**PostgreSQL 16+** становится основным production-backend для master. SQLite остаётся для локального/одиночного развёртывания. Реализуется **два backend'а за общим интерфейсом**, а не замена одного другим.

Это соответствует ADR-0004 §4.1 и не усложняет простые установки.

### 6.2. Структура storage-слоя

```text
storage/
├── base.py                 # общий интерфейс: connection, transaction, stores
├── sqlite/
│   ├── db.py
│   ├── schema.py
│   └── stores/
└── postgres/
    ├── db.py
    ├── schema.py
    └── stores/
```

API получает хранилище через фабрику:

```python
storage = create_storage(settings)  # выбор по DSN
```

а не импортирует `sqlite3`-реализацию напрямую. Это устраняет текущую привязку `api/app.py:20`.

### 6.3. Конфигурация

```text
APPSECGATE_MASTER_DATABASE_URL=postgresql://user:pass@host:5432/appsecgate
```

- DSN однозначно определяет backend; явный `backend` не обязателен.
- Старый `APPSECGATE_MASTER_DB` сохраняется для SQLite.
- **Пароль и полный DSN не выводятся в логи.** Redaction на уровне конфига.

### 6.4. Драйвер

**psycopg 3** (sync) как основной драйвер; при необходимости — `asyncpg` для FastAPI. Окончательный выбор фиксируется в PR реализации, но не меняет архитектурных решений этого ADR.

Новая зависимость — только в `appsecgate-master/pyproject.toml`. `mcp-server` не затрагивается (G7 ADR-0004).

### 6.5. Схема PostgreSQL

| SQLite | PostgreSQL | Комментарий |
|---|---|---|
| `?` placeholders | `%s` (psycopg) | Параметризация драйвера |
| `INSERT OR REPLACE` | `INSERT ... ON CONFLICT ... DO UPDATE/NOTHING` | Явная семантика upsert |
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGINT GENERATED ALWAYS AS IDENTITY` | Стандарт SQL:2003 |
| `TEXT` для JSON | `JSONB` | Индексируемость, валидация |
| `TEXT` для timestamps | `TIMESTAMPTZ` | Корректная работа с TZ, сортировка |
| `RAISE(ABORT)` в триггерах | PL/pgSQL `RAISE EXCEPTION` | Триггеры append-only |
| `sqlite_master` / `sqlite_sequence` | `information_schema` / `pg_catalog` | Управление схемой через DDL |
| — | Декларативное партиционирование | Monthly partitions для `events` и `audit_log` |

**Особое внимание:** при переводе timestamps в `TIMESTAMPTZ` необходимо проверить сериализацию обратно в UTC ISO-8601 и детерминированную сортировку `(at, event_id)` — это контракт ADR-0006 §3.4.

### 6.6. Транзакции и конкурентная идемпотентность

Текущая последовательность в SQLite (SELECT → INSERT → audit → пересчёт aggregate) в PostgreSQL заменяется на:

1. `INSERT INTO events (...) ON CONFLICT (client_event_id) DO NOTHING RETURNING id`
2. Если `RETURNING` пуст — duplicate, пишем `duplicate` в audit (вне основной транзакции или в отдельной).
3. Если принято — `INSERT INTO audit_log (...) VALUES (...)`.
4. Обновление агрегата `(project_key, fp)` — в **той же транзакции**, что и событие + audit.

**Транзакционные границы (явно):**

- Событие + accepted-аудит + обновление агрегата — **одна транзакция**.
- Ошибка посередине batch: валидные события принимаются, невалидные отклоняются с записью в audit (семантика batch из ADR-0004 не меняется).
- Параллельные события для одного `(project_key, fp)`: сериализуются через row-level lock на агрегате или через `ON CONFLICT` на агрегате.

Это устраняет гонку `SELECT`+`INSERT`, которая в SQLite была скрыта файловой блокировкой.

### 6.7. Схема и миграции

- Первая PostgreSQL-версия создаёт чистую схему.
- **Drop-on-mismatch для PostgreSQL нельзя реализовывать безотносительно базы**: удаляются только объекты AppSecGate в выделенной PostgreSQL schema (`appsecgate`), а не вся база.
- Перенос существующих SQLite-данных не делается (pre-release). Если данные ценны — отдельный экспорт/импорт event-log + rebuild aggregates.

### 6.8. Docker Compose

Добавляется сервис PostgreSQL:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    volumes:
      - pg-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U appsecgate"]
    environment:
      POSTGRES_USER: appsecgate
      POSTGRES_DB: appsecgate
      POSTGRES_PASSWORD_FILE: /run/secrets/pg_password
    secrets:
      - pg_password

  master:
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      APPSECGATE_MASTER_DATABASE_URL: postgresql://appsecgate:${PG_PASSWORD}@postgres:5432/appsecgate
```

- Master остаётся non-root с read-only rootfs.
- SQLite-volume в PostgreSQL-режиме не монтируется.
- DSN/credentials — через секреты.

### 6.9. Фундамент авторизации (задел на Phase 3)

> **Это ключевое расширение ADR.** Модель авторизации выбирается **сейчас**, но реализуется поэтапно: API-key слой в Phase 2, user RBAC в Phase 3. Схема и RLS-политики не меняются при переходе.

#### 6.9.1. Принципы

1. **Единый механизм изоляции — RLS.** И для API-ключа, и для пользователя. Никаких `WHERE project_key = ?` в приложении.
2. **Principal-agnostic RLS.** Политика не знает, кто ты — ключ или пользователь. Она вызывает функцию `app.current_can_access_project(project_key)`, которая резолвит в зависимости от `app.principal_type`.
3. **Fail-closed.** Если контекст не установлен — 0 строк.
4. **Append-only на уровне БД.** Даже `admin` не может `UPDATE/DELETE` `events`/`audit_log` — только триггеры и роль без прав.
5. **Аудит actor'а** — `api-key:<id>` или `user:<id>` в `audit_log`. Схема не меняется.

#### 6.9.2. Модель данных

**Phase 2 (активные):**

```sql
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_hash TEXT NOT NULL UNIQUE,          -- sha256(raw_key)
    project_key TEXT NOT NULL,
    label TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('reader','writer','admin')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by UUID,                        -- FK users, nullable в Phase 2
    revoked_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ
);
CREATE INDEX idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX idx_api_keys_project ON api_keys(project_key) WHERE revoked_at IS NULL;
```

**Phase 3 (схема создаётся сейчас, таблицы пустые в Phase 2):**

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE,
    display_name TEXT,
    oidc_subject TEXT UNIQUE,               -- sub из IdP
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    disabled_at TIMESTAMPTZ
);

CREATE TABLE roles (
    id TEXT PRIMARY KEY,                    -- 'admin','appsec','developer','viewer'
    description TEXT
);
INSERT INTO roles (id, description) VALUES
  ('admin',     'Full access to master'),
  ('appsec',    'Triage findings, manage suppressions'),
  ('developer', 'Read findings for own projects'),
  ('viewer',    'Read-only access to assigned projects');

CREATE TABLE project_memberships (
    user_id UUID NOT NULL REFERENCES users(id),
    project_key TEXT NOT NULL,
    role_id TEXT NOT NULL REFERENCES roles(id),
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by UUID REFERENCES users(id),
    revoked_at TIMESTAMPTZ,
    PRIMARY KEY (user_id, project_key)
);
CREATE INDEX idx_memberships_user    ON project_memberships(user_id)     WHERE revoked_at IS NULL;
CREATE INDEX idx_memberships_project ON project_memberships(project_key) WHERE revoked_at IS NULL;

CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);
```

**В Phase 2:** `api_keys` populate'ится, остальные таблицы существуют, но пусты. Никаких `ALTER TABLE` в Phase 3.

#### 6.9.3. RLS-фундамент

```sql
CREATE SCHEMA app;

CREATE FUNCTION app.current_can_access_project(p_project_key TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql STABLE
AS $$
DECLARE
    v_type  TEXT := current_setting('app.principal_type', true);
    v_id    TEXT := current_setting('app.principal_id',   true);
    v_proj  TEXT := current_setting('app.current_project', true);
BEGIN
    -- Phase 2: API key — проект жёстко привязан к ключу
    IF v_type = 'api_key' THEN
        RETURN p_project_key = v_proj AND v_proj IS NOT NULL;
    END IF;
    -- Phase 3: user — проверка членства
    IF v_type = 'user' THEN
        RETURN EXISTS (
            SELECT 1 FROM project_memberships
            WHERE user_id     = v_id::uuid
              AND project_key = p_project_key
              AND revoked_at  IS NULL
        );
    END IF;
    RETURN FALSE;  -- fail-closed
END;
$$;
```

Политика на каждой таблице:

```sql
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE events FORCE  ROW LEVEL SECURITY;

CREATE POLICY project_isolation ON events
    USING (app.current_can_access_project(project_key));

-- аналогично для aggregates, audit_log, api_keys, project_memberships, sessions
```

**Phase 2** упражняет только ветку `api_key`. **Phase 3** — ветку `user`. Политики не меняются.

#### 6.9.4. Auth-flow

**Phase 2 (сейчас):**

```
Bearer <raw_key>
  │ sha256(raw_key) → lookup api_keys.key_hash
  │ validate: exists, not revoked, not expired, scope ∈ {reader, writer, admin}
  │ resolve: project_key, key_id
  ▼
SET LOCAL app.principal_type  = 'api_key';
SET LOCAL app.principal_id    = '<key_id>';
SET LOCAL app.current_project = '<project_key>';
```

**Phase 3 (позже):**

```
Session cookie / OIDC token
  │ validate session / OIDC sub
  │ resolve: user_id
  │ project context — из URL / сессии
  ▼
SET LOCAL app.principal_type  = 'user';
SET LOCAL app.principal_id    = '<user_id>';
SET LOCAL app.current_project = '<project_key>';
```

Один и тот же код установки контекста; различается только источник principal'а.

#### 6.9.5. Failure modes (общие для REST и MCP)

| Ситуация | Ответ | Комментарий |
|---|---|---|
| Нет `Authorization` header | `401` | Без деталей |
| Ключ не найден (sha256 mismatch) | `401` | Без деталей |
| Ключ revoked / expired | `401` + audit `auth_revoked`/`auth_expired` | |
| Scope недостаточен | `403` | |
| RLS: запрос к чужому проекту | **Пустой результат** (не 403) | Не раскрывать существование |
| Контекст не установлен | 0 строк (fail-closed) | Ошибка конфигурации |
| Rate-limit | `429` + `Retry-After` | |

**Принцип:** не раскрывать существование чужих данных. На чужой проект — пустой результат, не 403.

#### 6.9.6. Аудит авторизации

```sql
CREATE TABLE audit_log (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at TIMESTAMPTZ NOT NULL DEFAULT now(),
    project_key TEXT,
    actor TEXT NOT NULL,        -- 'api-key:<id>' | 'user:<id>' | 'system'
    event TEXT NOT NULL,        -- 'auth_ok' | 'auth_failed' | 'tool_call' | 'event_accepted' | ...
    payload JSONB NOT NULL
);

CREATE TRIGGER audit_log_no_modify
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION app.raise_append_only();
```

Схема не меняется при переходе Phase 2 → Phase 3. Меняется только значение `actor`.

#### 6.9.7. Что реализуется в Phase 2, а что — заглушка

| Компонент | Phase 2 | Phase 3 |
|---|---|---|
| `api_keys` | ✅ populate, validate | ✅ продолжает работать (service-to-service) |
| `users` | ⬜ таблица пустая | ✅ populate через OIDC/manual |
| `roles` | ✅ справочник создан | ✅ используется |
| `project_memberships` | ⬜ таблица пустая | ✅ populate |
| `sessions` | ⬜ таблица пустая | ✅ populate |
| `app.current_can_access_project()` | ✅ только ветка `api_key` | ✅ обе ветки |
| RLS-политики | ✅ созданы | ✅ не меняются |
| OIDC | ❌ | ✅ |
| UI управления пользователями | ❌ | ✅ |
| `audit_log.actor` | `api-key:<id>` | `user:<id>` или `api-key:<id>` |

#### 6.9.8. Миграционный путь Phase 2 → Phase 3

1. Включить OIDC-провайдер (Keycloak/Authentik/корпоративный IdP) — конфиг, не схема.
2. Заполнить `users`, `project_memberships` из текущих `api_keys` (сервисные аккаунты становятся user'ами с ролью `developer`).
3. Включить session-based auth-flow рядом с API-key flow.
4. `api_keys` остаются для edge (service-to-service) — не удаляются.
5. **Схема и RLS-политики не меняются.**

---

## 7. Последствия

### 7.1. Положительные

- Master выдерживает конкурентные push'и и мультикомандное развёртывание.
- RLS — единый механизм изоляции для Phase 2 и Phase 3.
- Схема авторизации не ломается при переходе на user RBAC — нет `ALTER TABLE`, нет переписывания политик.
- Append-only на уровне ядра.
- Сетевой протокол открывает путь к MCP для master (ADR-0013).
- SQLite остаётся для solo-сегмента — продукт не теряет доступность.
- Схема содержит задел на Phase 3 — таблицы создаются сейчас, но не используются.

### 7.2. Отрицательные / риски

- Новая production-зависимость `psycopg` в `appsecgate-master`.
- Усложнение Docker Compose (сервис PostgreSQL, healthcheck, секреты).
- Дублирование store-реализаций (SQLite + PostgreSQL) — цена за прозрачность абстракции.
- Тесты требуют реального PostgreSQL (не только мок драйвера).
- Схема содержит таблицы, которые пока не используются (`users`, `roles`, `project_memberships`, `sessions`) — цена за отсутствие будущих миграций.

### 7.3. Нейтральные

- `mcp-server/pyproject.toml` не меняется.
- Внешние контракты API не меняются.
- Локальные SQLite-базы разработчиков не затрагиваются.

---

## 8. План внедрения

| # | Содержание | Зависит |
|---|---|---|
| **DB-1** | Общий storage-интерфейс (`base.py`), фабрика `create_storage(settings)`, сохранение SQLite backend без регрессий | — |
| **DB-2** | PostgreSQL backend: `db.py`, `schema.py`, stores (events, aggregates, audit) | DB-1 |
| **DB-3** | Транзакции: event + audit + aggregate в одной транзакции; `INSERT ... ON CONFLICT` для дедупликации | DB-2 |
| **DB-4** | Append-only триггеры (PL/pgSQL) + RBAC (RLS, роль приложения) | DB-2 |
| **DB-5** | **Auth-фундамент:** таблицы `api_keys`, `users`, `roles`, `project_memberships`, `sessions`; функция `app.current_can_access_project()`; RLS-политики на всех таблицах | DB-4 |
| **DB-6** | **Auth-flow Phase 2:** Bearer → sha256 lookup → SET LOCAL → RLS. Failure modes, аудит auth | DB-5 |
| **DB-7** | Конфигурация: `APPSECGATE_MASTER_DATABASE_URL`, redaction DSN в логах | DB-2 |
| **DB-8** | Docker Compose: сервис PostgreSQL, healthcheck, секреты; обновление `docs/deploy-master.md` | DB-7 |
| **DB-9** | Интеграционные тесты на реальном PostgreSQL; матрица обоих backend'ов; `make check` зелёный | DB-2..8 |

**Phase 3 (отдельный ADR):** OIDC, populate `users`/`memberships`, session-flow, UI управления пользователями.

---

## 9. Отложенное решение: ClickHouse

### 9.1. Роль ClickHouse

ClickHouse — мощная колоночная СУБД для OLAP-нагрузок. Его место в архитектуре AppSecGate — **аналитический контур Phase 4** (дашборды, ad-hoc аналитика по годам данных, агрегации по миллионам событий). Он **не заменяет** PostgreSQL как system of record.

### 9.2. Почему не сейчас

- **Профиль нагрузки** (§4) — умеренный OLTP, PostgreSQL с избытком достаточно.
- **Транзакционная идемпотентность** — ClickHouse не даёт полноценных ACID и уникальных ограничений в привычном смысле; дедупликация по `client_event_id` потребовала бы эмуляции на уровне приложения.
- **RBAC** — RLS в ClickHouse отсутствует в привычном виде; изоляция проектов сложнее.
- **Операционная сложность** — MergeTree, TTL, отдельный бэкап, отдельный мониторинг; на текущем этапе это преждевременно.
- **Группы пользователей** (§5) — ни одна из четырёх групп не требует ClickHouse на текущем этапе.

### 9.3. Критерии перехода

ClickHouse вводится как **дополнение** к PostgreSQL (а не замена), когда выполнено хотя бы одно:

1. **Объём событий** превышает **50–100 млн событий/день** устойчиво (не пиково).
2. **Phase 4 (дашборды)** требует sub-second агрегаций по данным за несколько лет, которые PostgreSQL не вытягивает даже с партиционированием и материализованными view.
3. **Ad-hoc аналитика** по event-log становится регулярной задачей AppSec/руководителей, а не эпизодической.

При наступлении критериев — отдельный ADR с дизайном гибридной схемы (PostgreSQL + ClickHouse, паттерн TRON.ASOC).

### 9.4. Компетенция

В команде есть экспертиза по ClickHouse (владелец продукта), что делает будущий переход реалистичным и снижает риск. Это не аргумент за внедрение сейчас, но аргумент за то, что отложенное решение — не «навсегда».

---

## 10. Альтернативы

| Альтернатива | Вердикт | Обоснование |
|---|---|---|
| **Оставить только SQLite** | ❌ | Не выдерживает мультикомандное развёртывание, конкурентные push'и, RBAC, MCP по сети |
| **PostgreSQL как единственный backend** (удалить SQLite) | ❌ | Отрезает solo-сегмент, усложняет простые установки; противоречит ADR-0004 |
| **ClickHouse как основной backend** | ❌ | Не OLTP; нет полноценных ACID/уникальных ограничений; RBAC сложнее; операционная сложность не оправдана объёмами |
| **Гибрид PostgreSQL + ClickHouse сразу** | ❌ | Преждевременная оптимизация; добавляет сложность без выгоды при текущем профиле |
| **MongoDB / документная БД** | ❌ | Не даёт транзакционной идемпотентности в нужном виде; RBAC слабее; нет преимуществ перед PostgreSQL для event sourcing |
| **MySQL / MariaDB** | ⚠️ | Технически возможно, но PostgreSQL выигрывает по RLS, JSONB, партиционированию, MCP-экосистеме |
| **Приложение-фильтрация вместо RLS** | ❌ | Легко забыть `WHERE project_key`; RLS — fail-closed по умолчанию |
| **Только API-key без фундамента Phase 3** | ❌ | Приведёт к `ALTER TABLE` и переписыванию политик в Phase 3 |

---

## 11. Тестирование

Недостаточно прогнать существующие тесты только на SQLite. Нужна **матрица проверок на обоих backend'ах**:

- Одинаковые store/API contracts.
- `accepted` / `duplicate` / `rejected`.
- Параллельная отправка одинакового `client_event_id` (concurrency test).
- Запрет `UPDATE`/`DELETE` для `events` и `audit_log` (append-only parity).
- Parity агрегатов после одинакового event-log.
- Фильтры findings и пагинация audit.
- Reconnect/retry и недоступность PostgreSQL.
- Полный путь edge → PostgreSQL master → CI.
- `make check` для всего репозитория.
- Реальный Docker Compose сценарий.

**Auth-тесты (Phase 2):**

- Валидный ключ → доступ к своему проекту.
- Невалидный / revoked / expired → 401.
- Ключ проекта A → пустой результат по проекту B (не 403).
- Контекст не установлен → 0 строк.
- Rate-limit → 429.
- Аудит `auth_ok`/`auth_failed` пишется.

**Задел на Phase 3:**

- Симуляция `principal_type='user'` + populate `project_memberships` → RLS возвращает правильный набор (без OIDC, только unit-тест функции `current_can_access_project`).
- Отсутствие membership → пустой результат.

Фикстуры (`appsecgate-master/tests/conftest.py:13`) сейчас создают SQLite напрямую — потребуется параметризация и реальный экземпляр PostgreSQL для интеграционных тестов (не только мок драйвера).

---

## 12. Открытые вопросы

1. **Драйвер:** `psycopg 3` vs `asyncpg` — финальный выбор в PR реализации, не влияет на архитектуру.
2. **Партиционирование:** monthly partitions для `events` и `audit_log` — с какого объёма включать (рекомендация: сразу, с запасом).
3. **Миграции:** инструмент (Alembic, собственный runner) — отдельный ресёрч; на первом этапе — чистая схема.
4. **Managed PostgreSQL vs self-hosted:** для корпоративного заказчика — оба варианта; документация должна покрывать оба.
5. **OIDC-провайдер для Phase 3:** Keycloak vs Authentik vs корпоративный — отдельный ADR.
6. **Роли Phase 3:** `admin`/`appsec`/`developer`/`viewer` — черновик; финализировать в Phase 3.

---

## 13. Ссылки

- ADR-0004 (master server) — §4.1 (PostgreSQL как опция), §5.2 (REST API), §5.4 (аудит append-only)
- ADR-0006 (lifecycle model) — §3.4 (master merge), §3.5 (cross-source consistency)
- ADR-0013 (MCP master) — использует auth-фундамент этого ADR
- `docs/architecture.md` §3.5 (storage layer), §8 (границы фаз)
- `appsecgate-master/src/appsecgate_master/storage/` — текущая SQLite-реализация
- `appsecgate-master/src/appsecgate_master/api/config.py:26` — текущая конфигурация
- `appsecgate-master/src/appsecgate_master/api/app.py:20` — текущая инициализация в lifespan
- `docker-compose.yml:19` — текущий `master-data` volume

---

## 14. Итог

- **PostgreSQL 16+** — основной production-backend для master; SQLite остаётся default для локального/одиночного развёртывания.
- Переход реализует опцию, уже предусмотренную ADR-0004 §4.1; архитектурное направление не меняется.
- Ключевая сложность — не REST API и не бизнес-логика, а аккуратный перенос storage-слоя, транзакций, append-only ограничений и конкурентной идемпотентности.
- **Auth-фундамент (расширение):** таблицы `api_keys`, `users`, `roles`, `project_memberships`, `sessions`; функция `app.current_can_access_project()`; RLS-политики — **создаются сейчас, работают для Phase 2 (api_key) и Phase 3 (user) без изменений**.
- **Phase 2 реализует только API-key слой.** Остальные таблицы — заглушки, populate в Phase 3.
- RBAC через RLS, MCP для master через read-only роль (ADR-0013), сетевой протокол PostgreSQL — фундамент для мультикомандного и мультиагентного сценариев.
- **ClickHouse не внедряется на этом этапе.** Отложен до Phase 4 с явными критериями перехода (§9.3) и с учётом имеющейся в команде экспертизы. Это соответствует паттерну конкурентов (TRON.ASOC, Snyk/SonarQube) и не является преждевременной оптимизацией.
- Минимальный правильный результат: общий storage-интерфейс, сохранённый SQLite без регрессий, PostgreSQL с идентичным поведением, корректные транзакции и конкурентная дедупликация, auth-фундамент с заглушками на Phase 3, Docker Compose и документация, интеграционные тесты на реальном PostgreSQL, зелёный `make check`.

---

## 15. Изменения в `docs/adr/README.md`

```markdown
| ADR | Название | Статус |
|---|---|---|
| ADR-0001 | Fingerprint and semantic dedup | Accepted |
| ADR-0003 | CI unresolved local delivery | Paused (superseded in parts by ADR-0006) |
| ADR-0004 | Master server sync | Paused (superseded in parts by ADR-0006) |
| ADR-0005 | Project reconciliation & shown state machine | Accepted (дополнен ADR-0006) |
| ADR-0006 | Unified finding lifecycle model | Accepted |
| ADR-0007 | Per-branch state | Proposed (Фаза 3) |
| ADR-0008 | Orchestrator presets | Accepted |
| ADR-0012 | Master database and auth foundation | **Proposed** |
| ADR-0013 | Master MCP interface | **Proposed** (зависит от 0012) |
```