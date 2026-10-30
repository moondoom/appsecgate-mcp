# План E2E-тестирования AppSecGate MCP на проекте-полигоне

Статус: **итерация 1 выполнена 2026-10-14 — 17/17 сценариев, 100%**,
**итерация 2 выполнена 2026-10-30 — 28/28 (100%)**
(`docs/reports/e2e-report-2026-10-30.md`, T14):
staged-diff (B5), verify_fix=fixed/wont_fix, IaC-фикстура (D4), память (E1),
перепроверка B2 после фикса T10, фикстуры в git (E4).
Есть 310 юнит/интеграционных тестов (мок-сканеры, tmp-SQLite); E2E на
реальном проекте и реальных бинарниках здесь не покрывался.

Цель: пройти весь цикл воронки §7.3 — scan → context → fix → verify — на
проекте-полигоне и зафиксировать критерии выхода §7.1–7.2.

## 1. Проект-полигон

Готовое репо с намеренными уязвимостями:

```
mcp-server/tests/fixtures/vuln-project/
├── .appsecgate-mcp/config.yaml   # низкие пороги, локальные gates
├── pyproject.toml               # устаревшие зависимости (метаданные проекта)
├── requirements.txt             # пины устаревших версий (Trivy/SCA)
├── main.tf                      # IaC-мисконфигурации (Trivy misconfig, D4)
├── secrets.py                   # фиктивные AWS key, AWS secret, GitHub PAT
├── sql_injection.py             # SQL-инъекция (Semgrep SAST)
└── xss.py                       # Jinja2 без autoescape → XSS (Semgrep SAST)
```

Матрица «файл → ожидаемая категория» (по фактическим детектам, E2E-report §2):

| Файл                | Категория | Сканер        | Что ожидаем |
|---------------------|-----------|---------------|-------------|
| `secrets.py`        | secret    | Gitleaks      | 1 находка: `github-pat`+`generic-api-key` на одной строке схлопываются дедупом (T1-фикс). AWS-примеры — документационные, Gitleaks их игнорирует |
| `sql_injection.py`  | sast      | Semgrep       | ≥ 1 находка (hardcoded SQL-выражение) |
| `xss.py`            | sast      | Semgrep       | ≥ 1 находка (jinja2-autoescape-false; CWE-116) |
| `requirements.txt`  | sca       | Trivy         | ≥ 1 находка (19 CVE: flask/requests/urllib3) |
| `pyproject.toml`    | sca       | Trivy         | 0 ожидаемо — без lock/manifest Trivy уязвимости не детектит |
| `main.tf`           | iac       | Trivy         | ≥ 1 находка (AVD-*: S3 public ACL, IAM full access, RDS password) |

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

- `scan_file` на каждый из 5 файлов по отдельности (включая `main.tf` — D4).
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

**Итерация 2 (T14):** `verify_fix` на **rw-копии** полигона (проект-полигон
смонтирован `:ro`, правки только во временной копии):
- `verify_fix(finding_id, "wont_fix", note)` → `verified_status=wont_fix`,
  `verified=true` (перескана нет);
- после реального фикса файла (`verify_fix(finding_id, "fixed")`) →
  `verified_status=fixed`, `verified=true`;
- `verify_fix_batch([fixed, not_fixed])` → `summary={fixed:1, not_fixed:1}`.

### 4.4 Suppression и feedback

- `suppress_finding(rule_id)` на одну находку — local scope.
- Повторный скан: находка скрыта локально, но остаётся в `shown_findings`.
- `submit_feedback` для находки — пишется в `feedback`.
- `export_snapshot` — JSON со сводкой и перечнем находок.
- `get_scan_history` — история сканов и `ruleset_hash` в каждом.

## 5. Регрессия T1 — «двоение» находок (проверка фикса)

Сценарий (проходит с дедупом уровня 1–2, `deduplicate` + `deduplicate_families`):

1. `scan_file secrets.py` (конфиг: `scanners.secrets.tool: gitleaks` — tool
   скалярный, §10.4; поведение с двумя адаптерами покрыто юнит-тестом
   `test_scan_dedups_same_secret_across_scanners`).
2. Ожидание: два правила Gitleaks (`github-pat`, `generic-api-key`) на **одной
   строке** (один и тот же секрет) — **одна** находка в ответе скана, не две
   (уровень 1 схлопывает только дубликаты РАЗНЫХ сканеров; «семьи» одного
   сканера по-прежнему склеивает уровень 2 по `(file, window//20, тело)` — T13).
3. Подтверждено E2E: `scan_file secrets.py` → total=1 (`github-pat`).

Проверка семантики дедупа:
- Разные секреты в одном файле — разные находки.
- Один секрет на разных строках одного файла, но с разным текстом —
  находки сохраняются (пузырь всегда уникален по сниппету/значению).

**B2 (T14, перепроверка после фикса T10):** повторный `scan_file secrets.py`
в одной сессии → **идентичный** набор fingerprint в обоих ответах
(детерминированный tie-break `(severity, scanner_priority, rule_id)` в дедупе).

## 6. Нефункциональные измерения (§6.2)

Замеры выполняются по ходу E2E-прогона (`scripts/e2e_measure/`):
- Длительность `scan_project` берётся из `meta.duration_ms` ответа скана.
- Пиковая память — семплинг `docker stats --no-stream` по контейнерам образа
  во время прогона (0.1 c шаг).
- Размер `shown_findings` + `finding_context` — после полного цикла по SQLite
  (page_count × page_size).

Целевые значения (см. E2E-report §4):
- Длительность `scan_project` полного полигона (target: < 30 c).
- Пиковое потребление памяти контейнера (target: < 512 МБ).
- Размер `shown_findings` + `finding_context` в SQLite после полного цикла.
- duration_ms из `ScanMeta` каждого скана (обязательное поле для NF-отчёта).

**E1 (T14, память на крупном полигоне):** `scan_project` на копии полигона +
120 файлов с SQLi (>120 файлов всего) под `--memory=512m`; пиковая память —
семплинг `docker stats` (0.2 c шаг) по именованному контейнеру. PASS = скан
завершился без `meta.errors` и без OOM (контейнер жив до конца скана).

## 7. Параллельные сессии

1. Сессия A — полигон `vuln-project` (mount `/workspace`).
2. Сессия B — временный второй проект (`mcp-server/tests/fixtures/other-project`,
   копия полигона без секретов; mount `/workspace-b`).
3. Параллельно прогоняем `scan_project` в обеих — ожидаем независимые
   `project_id` и раздельные записи в БД.

Особенности прогона:
- `project_id = sha256(realpath(project_path))` (§4.7) — при одинаковом
  контейнерном пути оба проекта дали бы один id. В харнессе проекты
  монтируются в разные пути.
- Тест параллельных сессий выполняется **до** мутаций (suppress): suppression
  хранится по fingerprint без project_id и глобально фильтрует равные находки
  в любом проекте (см. E2E-report OBS-2).
- Для корректного изолированного прогона используется свежий data volume.

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

- Прогон выполняется через `scripts/e2e_measure/` (автоматизация; MCP-клиент
  поднимает контейнеры в stdio-режиме).
- Ручные сценарии (§3.4–3.5 — `update_config` локально; §4.3 — контекст-пакет).
- Результаты зафиксированы в `docs/reports/e2e-report-2026-10-30.md`.

## 10. Примечания (по итогам прогона 2026-10-14)

1. `update_config` в Docker **не тестируется** — `.appsecgate-mcp` смонтирован `:ro`.
   Прогоняется локально через `mcp-server/.venv/bin/appsecgate-mcp` (без Docker).
   Результаты: валидный update → `updated`; неверный **тип** → `invalid` (файл не
   меняется); **неизвестное поле** молча дропается и уходит в файл (см.
   E2E-report OBS-3 — кандидат в задачи).
2. `verify_fix` проверяет `not_fixed`-путь (файл не менялся — проект `:ro`):
   сервер возвращает `status: ok, verified_status: not_fixed, verified: true`,
   и этот же fingerprint после перескана. `fixed`-путь — локально при
   редактируемом проекте.
3. `scan_diff` работает по untracked-файлам полигона (git init выполнен; все
   файлы untracked) — найдено 4 файла/4 находки.
4. Регрессия T1 (§5) — `scanners.secrets.tool` скалярный; тестируется с
   `gitleaks`. Дедуп проверяется на двойном срабатывании gitleaks в одной
   строке (2 raw-находки → 1 в ответе). Семантика «разные секреты/строки →
   разные находки» подтверждена family-дедупом (§5 плана; тест
   `test_scan_dedups_same_secret_across_scanners` + E2E).
5. Для параллельных сессий создан `mcp-server/tests/fixtures/other-project/`;
   монтируется в `/workspace-b` для различных `project_id`.
6. Фикстуры уточнены по факту: `xss.py` — jinja2 autoescape (иначе правил на
   flask f-string нет); добавлен `requirements.txt` для Trivy/SCA
   (pyproject без lock не детектится); `secrets.py` — 1 находка после дедупа.

## 11. Инструментарий

- **Автоматический:** `scripts/e2e_measure/` — полный цикл воронки
  (`scan_file`/`scan_diff`/`scan_project`, `query_findings_db`, `get_fix_context`
  + batch, `verify_fix`, `suppress_finding`, `submit_feedback`,
  `get_scan_history`, `export_snapshot`), NF-замеры (§6), параллельные сессии
  (§7). Для изоляции создаёт свежий data volume на прогон.
- **Ручной прогон:** MCP-клиент (Cline/Continue) — инициализация (§3),
  контекст-пакеты (§4.3), `update_config` локально (§3.4–3.5).
- Результаты — в `docs/E2E-report-<дата>.md`.
## 12. Итерация 2 (T14, 2026-10-30): добавленные сценарии

Новые шаги `scripts/e2e_measure/` (общие: временная копия полигона через
`tempfile`, свежий data volume — suppression по fingerprint глобален, OBS-2):

1. **B5 — staged/unstaged/untracked/clean/регрессия** (`run_git_diff_scenarios`):
   temp-копия, `git init` + baseline-коммит, затем:
   - staged-файл (`staged_secret.py`, `git add`) + unstaged-правка
     (`sql_injection.py`) + untracked-файл (`untracked_vuln.py`) → один
     `scan_diff` видит все три класса;
   - после `git commit` → `scan_diff` возвращает 0 (граница clean-tree);
   - `git revert HEAD` + `git reset --soft HEAD~1` → staged-регрессия против
     старого коммита → `scan_diff` детектит возврат SQLi.
2. **verify_fix fixed/wont_fix** (`run_fix_verify_scenarios`) — rw-монтаж
   temp-копии (`read_only=False`): wont_fix (note, без перескана) → fixed
   (реальная правка файла хостом) → batch `[fixed, not_fixed]`.
3. **D4 — `main.tf`** в полигоне: Trivy misconfig (AVD-*), `scan_file(main.tf)`
   в funnel-цикле.
4. **E1 — память** (`run_memory_scenario`): крупный полигон (>120 py-файлов),
   `--memory=512m`, семплинг `docker stats` по именованному контейнеру.
5. **B2 — дедуп** (`dedup_stability_recheck`): два скана `secrets.py` →
   идентичный набор fingerprint (регресс T10).

Проверочный итог: сканеры, которые реально грузятся в контейнере
(gitleaks/trivy/semgrep), должны давать находки по всем фикстурам; при падении
`scan_file sql_injection.py/xss.py` с total=0 — смотреть `meta.errors`/warnings
(известный регресс: strip dist-info в Dockerfile ломал semgrep, см. OBS-6 в
E2E-report-2026-10-30).
