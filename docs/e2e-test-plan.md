# План E2E-тестирования AppSecGate MCP на проекте-полигоне

Статус: план (задача T3, `docs/open-tasks.md`). Зафиксировано 2026-10-13.
Есть 290 юнит/интеграционных тестов (мок-сканеры, tmp-SQLite); E2E на
реальном проекте и реальных бинарниках здесь не покрывается.

Цель: пройти весь цикл воронки §7.3 — scan → context → fix → verify — на
проекте-полигоне и зафиксировать критерии выхода §7.1–7.2.

## 1. Проект-полигон

Готовое репо с намеренными уязвимостями:

```
mcp-server/tests/fixtures/vuln-project/
├── .appsecgate-mcp/config.yaml   # низкие пороги, локальные gates
├── pyproject.toml               # устаревшие зависимости (Trivy/SCA)
├── secrets.py                   # фиктивные AWS key, AWS secret, GitHub PAT
├── sql_injection.py             # SQL-инъекция (Semgrep SAST)
└── xss.py                       # XSS (Semgrep SAST)
```

Матрица «файл → ожидаемая категория»:

| Файл                | Категория | Сканер        | Что ожидаем |
|---------------------|-----------|---------------|-------------|
| `secrets.py`        | secret    | Gitleaks      | ≥ 2 находки (AWS key, GitHub PAT) |
| `sql_injection.py`  | sast      | Semgrep       | ≥ 1 находка (SQLi) |
| `xss.py`            | sast      | Semgrep       | ≥ 1 находка (XSS) |
| `pyproject.toml`    | sca       | Trivy         | ≥ 1 находка (устаревшая зависимость) |

## 2. Предусловия

1. Образ собран: `make docker-build` (в корне репо).
2. Конфиг полигона лежит в `.appsecgate-mcp/config.yaml` (уже есть).
3. Хост-каталог для данных и кэша доступен на запись
   (`~/.appsecgate-mcp`, `appsecgate-cache`).
4. Сеть: `network_mode: none` — офлайн. Все правила — из Rules Bundle.

Запуск сервера в stdio-режиме с полигоном:

```bash
PROJECT_PATH=mcp-server/tests/fixtures/vuln-project \
  docker compose -f mcp-server/docker-compose.yml run --rm appsecgate-mcp
```

Для интерактивной прогонки — подключить MCP-клиент (см.
`docs/deploy-agents.md`) либо слать JSON-RPC по stdio.

## 3. Проверка инициализации

1. `session_start` с `project_path=<полигон>` — ожидаем `project_id`.
2. Повторный `session_start` с другим путём в той же сессии — ошибка
   (инвариант №6).
3. `get_config` — видим конфиг полигона (порог sast = low).
4. `update_config` с `stack.languages: [python]` — применяется без ошибок.
5. `update_config` с неизвестным полем — ошибка валидации
   (схема Config, новые поля запрещены).

## 4. Цикл воронки

### 4.1 session_start → сканы

- `scan_file` на каждый из 4 файлов по отдельности.
- `scan_diff` на `secrets.py` + `xss.py` (псевдодифф: список файлов).
- `scan_project` на весь полигон — announce-ответ (§4.3), без пометки SHOWN.

### 4.2 Запросы

- `query_findings_db` по проекту — все находки из `shown_findings`, только
  SELECT по публичным views (инвариант №5).
- Ожидаем: `finding_id` == `fingerprint` (16 hex), `rule_id` — имя правила.

### 4.3 Контекст и фикс

- `get_fix_context(finding_id)` для SQLi — контекст-пакет (данные, НЕ промпт).
- `get_fix_context_batch` на 2–3 finding_id из секретов + SQLi.
- `verify_fix`/`verify_fix_batch`: подаём «исправленный» сниппет
  (параметризованный SQL, экранированный вывод) — ожидаем resolved/valid.
- Повтор `scan_file` после «исправления»: те же logical_id отсутствуют.

### 4.4 Suppression и feedback

- `suppress_finding(rule_id)` на одну находку — local scope.
- Повторный скан: находка скрыта локально, но остаётся в `shown_findings`.
- `submit_feedback` для находки — пишется в `feedback`.
- `export_snapshot` — JSON со сводкой и перечнем находок.
- `get_scan_history` — история сканов и `ruleset_hash` в каждом.

## 5. Регрессия T1 — «двоение» находок (проверка фикса)

Сценарий (должен проходить с дедупом уровня 2, `deduplicate_families`):

1. В конфиге полигона включить оба секрет-сканера:
   `scanners.secrets.tool: gitleaks` + `trufflehog` (или оба адаптера).
2. `scan_file secrets.py`.
3. Ожидание: на **один и тот же секрет** (AWS key) — **одна** находка
   в ответе скана, не две. Критерий: `len(result["findings"])` по секретам
   == числу уникальных значений секретов в файле.

Проверка семантики дедупа:
- Разные секреты в одном файле — разные находки.
- Один секрет на разных строках одного файла, но с разным текстом —
  находки сохраняются (пузырь всегда уникален по сниппету/значению).

## 6. Нефункциональные измерения (§6.2)

На хосте проекта, не в контейнере:

```bash
/usr/bin/time -v docker compose -f mcp-server/docker-compose.yml \
  run --rm appsecgate-mcp scan-project ... 2>&1 | grep -E 'wall clock|Maximum resident'
```

Замеряем и фиксируем:
- Длительность `scan_project` полного полигона (target: < 30 c).
- Пиковое потребление памяти контейнера (target: < 512 МБ).
- Размер `shown_findings` + `finding_context` в SQLite после полного цикла.
- duration_ms из `ScanMeta` каждого скана (обязательное поле для NF-отчёта).

## 7. Параллельные сессии

1. Сессия A — полигон `vuln-project`.
2. Сессия B — временный второй проект (`mcp-server/tests/fixtures/other-project`,
   можно скопировать полигон без секретов).
3. Параллельно прогоняем `scan_project` в обеих — ожидаем независимые
   `project_id` и раздельные записи в БД.

## 8. Критерии выхода

Из §7.1–7.2:

1. Все шаги §4 выполнимы без ошибок; `meta.errors` пуст.
2. Каждая находка имеет непустой `fingerprint` и `rule_id`.
3. Нет ни одной находки вне скоупа проекта; пути относительные.
4. `query_findings_db` вернул только SELECT-вьюхи (инвариант №5).
5. Регрессия T1 из §5 проходит (дедуп активен).
6. NF-замеры §6 в целевом диапазоне.
7. Параллельные сессии §7 не пересекаются.

## 9. Организация

- Прогон выполняется вручную (Docker + MCP-клиент), автоматизация — позже,
  отдельным этапом.
- Результаты фиксируются в `docs/E2E-report-<дата>.md` (создаётся по
  итогам прогона, вне этого файла).