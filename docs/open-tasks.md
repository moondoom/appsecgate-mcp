# Открытые задачи Фазы 1

Зафиксировано по итогам проверки состояния Фазы 1 (2026-10-13).
Каждая задача — отдельный этап/PR. Перед реализацией — Plan-мод
(см. AGENTS.md, «Workflow: Plan vs Act»).

**Обновление 2026-10-13:** T1, T2, T3 решены (см. статус под каждой
задачей). T4 снята по решению владельца — новых правил не добавляем,
фактический охват приведён к срезу бандла (c, csharp, go, javascript,
python, scala, swift) в `SemgrepAdapter.supported_languages`, `_LANG_TAGS`,
`_SUPPORTED_EXTENSIONS`, `default_rulesets`, `config/default.yaml` и
`manifest.yaml`.

**Обновление 2026-10-14:**

По итогам E2E-прогона 17/17 сценариев (`docs/E2E-report-2026-10-14.md`)
и последующей инвентаризации выявленных проблем добавлены задачи T9–T15.
Новые наблюдения OBS-5 (недетерминированный дедуп, T10) и ранее
незафиксированные проблемы T11 (update_config в `:ro`), T12
(двойная семантика `status` у `verify_fix`), T13 (SCA: 19 CVE → 1 находка),
T14 (вторая итерация E2E) и T15 (UX rule_id). Самая важная — **T9**:
в Docker `project_id` вычисляется от контейнерного пути `/workspace`,
а не от реального host-проекта, поэтому все host-проекты, смонтированные
в `/workspace` при общем `appsecgate-data` volume, получают ОДИН и тот же
`project_id`; имя проекта при запуске MCP-сервера не передаётся
(`--project /workspace` зашит в docker-compose и конфиги клиентов),
`project_alias` всегда `workspace`.

---

## T1. Fingerprint «двоит» находки (решено ✅)

**Дизайн:** [ADR-0001](adr/ADR-0001-fingerprint-and-semantic-dedup.md).

**Статус:** реализован по ADR-0001 (детерминированный tie-break + `Deduplicator.deduplicate_families()`).
Пройдено 290 тестов, в том числе регрессия `test_scan_dedups_same_secret_across_scanners`.

Файлы: `normalization/dedup.py`, `orchestration/coordinator.py`.

## T2. Инструкция развёртывания для Continue / Cline / Claude Code (решено ✅)

**Статус:** создан `docs/deploy-agents.md` с каноническим именем `appsecgate`,
примерами конфигов для Continue, Claude Code, Cline, Cursor (кодовые блоки,
не рабочие файлы), словарём полей находки, шагами проверки и диагностикой.
Уточнено: «название проблемы» = `rule_id` + `message` (machine-readable на сервере,
агент формирует сводку). Рабочий конфиг `.continue/mcpServers/appsecgate.yaml`
переименован в `appsecgate`. README и `mcp-server/README.md` обновлены ссылками.

- В репо только `.continue/mcpServers/appsecgate.yaml` (имя сервера обновлено
  на `appsecgate`). Примеры конфигов в документе, не в рабочей директории.
- Инструкция содержит: каноническое имя MCP-сервера, готовые конфиги под
  каждый клиент, словарь полей находки, шаги проверки, диагностику.
- Корректное название проблемы: `rule_id` (+ `message` в скобках) — сервер
  отдаёт machine-readable; агент формирует сводку.

## T3. План тестирования MCP на тестовом проекте (решено ✅)

**Статус:** план создан (`docs/e2e-test-plan.md`), полигон
`mcp-server/tests/fixtures/vuln-project` + `other-project` подготовлены,
E2E **выполнен 2026-10-14 — 17/17 сценариев, 100%**
(отчёт `docs/E2E-report-2026-10-14.md`). Инструментарий:
`scripts/e2e_measure.py` (MCP-клиент, stdio-контейнеры, полный цикл воронки,
NF-замеры, параллельные сессии). Проверены: scan_file/scan_diff/scan_project,
query_findings_db (SELECT + блокировка UPDATE), get_fix_context(+batch),
verify_fix (not_fixed), suppress + rescan, feedback, history, export_snapshot,
две параллельные сессии (независимые project_id). Дедуп T1 подтверждён:
два gitleaks-правила на одной строке → одна находка.

- Критерии выхода §8 плана — все 7 выполнены.
- NF: scan_project 8.2–8.7 c (цель < 30 c); пиковая память контейнера ~482 MiB
  (цель < 512 MiB); SQLite после цикла — строки/размеры в отчёте §4.
- 290 юнит-тестов остаются зелёными (`make check`).

## T5. Redaction gap: `get_fix_context` window содержит сырые секреты (новое)

**Статус:** открыта (по итогам E2E, OBS-1).

`get_fix_context` возвращает snippet как `[REDACTED]`, но `window.lines`
(окно кода, строится из живого исходника) содержит сырые значения секретов
(`AKIA…`, `wJalr…`, `ghp_…` — подтверждено на полигоне). Инструкция `ContextPack`
«не восстанавливать redacted-значения» расходится с содержимым окна.

Варианты решения (на выбор владельца):
1. Маскировать в окне строки, где сработал секретный детект (или все строки
   secret-находки `line_start..line_end`).
2. Явно задокументировать, что окно кода — сырой проект (агент и так имеет
   доступ к ФС), и убрать инструкцию про redaction из окна.
Файлы: `orchestration/context_builder.py` (`_build_window`), `models/context.py`.

## T6. `update_config` не отклоняет неизвестные поля (новое)

**Статус:** открыта (по итогам E2E, OBS-3).

`update_config({"totally_unknown_field": 42})` → `status: updated`:
Pydantic v2 `extra=ignore` (в `Config` нет `extra="forbid"`), поле тихо
дропается при валидации, но записывается в `config.yaml` (пишется merged-dict).
Ошибки **типов** (`timeout_seconds: "abc"`) корректно дают `status: invalid`.

Ожидание AGENTS.md — «лишнее поле сломает валидацию». Решение: добавить
`model_config = ConfigDict(extra="forbid")` в `Config` (проверить влияние на
`config/default.yaml` и тесты) либо reject на уровне merge в `update_config`.

## T7. Скоп suppression: глобальный по fingerprint или проектный? (вопрос)

**Статус:** открыт вопрос (по итогам E2E, OBS-2).

`suppressions.fingerprint` — PK без `project_id`; `filter_active` фильтрует
находки ВСЕХ проектов/сессий по fingerprint. Один и тот же код (одинаковый
fingerprint) в другом проекте подавляется автоматически. Семантически это
«одна и та же проблема», но для мультипроектной установки нужно подтверждение:
- если дизайн «глобально» — задокументировать (это не баг);
- если «по проекту» — добавить `project_id` в `suppressions` и фильтр.
Артефактный эффект: E2E-параллельные сессии влияли друг на друга (см. plan §7).

## T8. `scan_project`: announce-only, но persist пишет в shown_findings (вопрос)

**Статус:** открыт вопрос (по итогам E2E, OBS-4).

`server.scan_project` вызывает `coordinator.scan([rel], mode="project")` без
`persist=False` — находки пишутся в shown_findings (статус SHOWN), хотя
комментарий и arch §4.3 декларируют «announce-only, без записи». Ответ остаётся
announce-форматом. Проверить намерение: если announce-only — передавать
`persist=False`; если запись разрешена — исправить комментарий/спеку.

## T9. `project_id` в Docker не зависит от проекта (P0, вопрос владельцу)

**Статус:** открыта критическая (по итогам E2E; см. также T7).

**Механизм.** `project_id = sha256(realpath(project_path))[:16]`
(`docs/fix-workflow-design.md` §4.10). Но реальный host-проект в сервер
**не передаётся** нигде по пути запуска:

- `docker-compose.yml` (docker-run.sh / compose MCP): env
  `APPSECGATE_PROJECT_PATH=/workspace` зашит жёстко; bind-mount
  `.:/workspace:ro` кладёт ЛЮБОЙ host-проект в один контейнерный путь.
- `.continue/mcpServers/appsecgate.yaml` и `docs/deploy-agents.md`: те же
  `-v .:/workspace:ro` + `--project /workspace`.
- `_resolve_default_project()` в `server.py` тоже отдаёт `/workspace`
  раньше, чем cwd.

**Следствия (эмпирически подтверждены в E2E):**
1. Два разных host-проекта, смонтированных в `/workspace` при общем
   volume `appsecgate-data`, получают **один и тот же** `project_id`
   (= `sha256("/workspace")[:16]`) → проектные записи, context, snapshot,
   suppressions перемешиваются между несвязанными проектами.
2. Один и тот же host-проект на двух машинах/в двух путях монтирования
   получает **разные** `project_id` → история верификаций и suppressions
   «теряется» между средами (непериодичность).
3. `project_alias` = basename = всегда `workspace` — бесполезен.
4. E2E-харнесс обходит баг: монтирует параллельные проекты в разные
   `mount_path` (`/workspace` vs `/workspace-b`) и свежие data-volume.

**Варианты решения (нужно решение владельца + правка §4.10):**
- А) Передавать идентичность явно: `--project-alias`/`APPSECGATE_PROJECT_ID`
  или `<project_name>` на старте; клиент (Continue/Cline) знает реальное имя.
- Б) Считать из содержимого смонтированного проекта: имя git-репозитория
  (`.git/config`) или хэш от него — детерминированно, без env.
- В) Оставить «один контейнер = один проект»: требовать для каждого
  проекта отдельный data-volume и/или key; задокументировать ограничение.
Файлы: `server.py` (`_compute_project_id`/`_resolve_default_project`),
`docker-compose.yml`, `scripts/e2e_measure.py` (`_docker_args`),
`.continue/mcpServers/appsecgate.yaml`, `docs/deploy-agents.md`, спека §4.10.

## T10. Недетерминированный дедуп → нестабильные fingerprint (P0, B1/OBS-5)

**Дизайн:** [ADR-0001](adr/ADR-0001-fingerprint-and-semantic-dedup.md).

**Статус:** открыта критическая (по итогам E2E, OBS-5). Реализовать по ADR-0001 (§3.2, детерминированный tie-break в `_collapse()`).

**Симптом (B1):** один и тот же секрет на одной строке получает то
`github-pat`, то `generic-api-key` fingerprint между прогонами. В дедупе
«выжившего» выбирает `_collapse()` в `normalization/dedup.py` по порядку
raw-находок Gitleaks — а порядок строк Gitleaks нестабилен между прогонами.

**Почему это ломает:** `fingerprint = sha256(rule_id + …)` — при смене
rule_id меняется fingerprint → suppression по старому fp не срабатывает,
`verify_fix` не находит находку, диффы `export_snapshot` шумят. Это же —
**наиболее вероятная причина B2** («5 строк в query_findings_db при 4
находках»: scan_file и scan_project дают разные rule_id/fingerprint для
одной строки).

**Направление фикса:** детерминированный tie-break в дедупе —
cортировка raw-находок перед `_collapse()` по стабильному ключу
`(severity, scanner_priority, rule_id)` + фиксированный приоритет
правил Gitleaks (github-pat > generic-api-key). Регресс-тест: два скана
одного файла → идентичный набор fingerprint. Затем перепроверить B2.

## T11. `update_config` пишет в проект: конфликт с `:ro` и инвариантом №1 (P1, A2/D3)

**Статус:** открыта (по итогам E2E).

`update_config` вызывает `_atomic_write` в `.appsecgate-mcp/config.yaml`
**внутри проекта** (дизайн §3.5). Локально работает. В каноническом
Docker-деплое проект смонтирован `:ro` (`docker-compose.yml`,
`.continue/mcpServers/appsecgate.yaml`) → запись упадёт с ошибкой ФС, а
если маунт случайно `rw` — это нарушение инварианта №1 («сервер НЕ пишет
файлы проекта. Никогда»).

**Варианты (вопрос владельцу):**
- А) Конфиг пишется в data-volume (вне проекта), проект остаётся `:ro`.
- Б) Задокументировать: `update_config` работает только при rw-монтаже
  проекта (local/dev); в Docker вернуть явную ошибку «read-only project».
- В) Отказаться от записи в проект: конфиг передаётся только через
  env/файл монтирования, `update_config` отклоняет запись.

## T12. `verify_fix`: двойная семантика `status` и `verified_status` (P1, C1)

**Статус:** открыта (по итогам E2E).

Ответ `verify_fix`: `"status": "ok"` (транспортный) +
`"verified_status": "fixed|not_fixed|wont_fix"` (результат верификации).
E2E-харнесс изначально читал только `status` и пропускал результат —
риск для LLM-агентов. Уточнить контракт: либо одно поле с результатом,
либо явная документированная иерархия (проверять `verified_status`),
либо `status` повторяет результат. Файлы: `server.py` (`verify_fix`,
`verify_fix_batch`), спека §5, E2E-харнесс.

## T13. SCA: 19 CVE схлопнуты в 1 находку (P2, B3)

**Дизайн:** [ADR-0001](adr/ADR-0001-fingerprint-and-semantic-dedup.md).

**Статус:** открыт вопрос (по итогам E2E). Реализовать по ADR-0001 (§12, п. 4).

Trivy находит 19 CVE в `requirements.txt`, но в нормализованном результате
остаётся **одна** находка (top CVE-2019-1010083): остальные 18 невидимы —
нет ни в `verify_fix`, ни в `export_snapshot`, ни в `query_findings_db`.
ADR-0001 фиксирует, что векторный подход не решает эту проблему — нужна
отдельная логика агрегации по пакету в `trivy.py`/нормалайзере. Нужно либо
перечислять все CVE, либо явно документировать «топ-1» как осознанный выбор.
Файлы: `normalization/`, `scanners/trivy.py`, спека §4.4.

## T14. Вторая итерация E2E: staged-diff, verify_fix-fixed, IaC, память (follow-up)

**Статус:** открыта (по итогам E2E 17/17; список недопокрытого).

1. **B5 — staged-покрытие:** полигон собран `git init` без коммитов, diff —
   только untracked. Добавить staged/unstaged/старый-коммит сценарии.
2. **verify_fix:** покрыты только `not_fixed`/`error`; добавить успешный
   `fixed` (перескан после реального фикса) и `wont_fix`.
3. **D4 — IaC-фикстуры:** критические `.tf`-файлы для Trivy
   (seed_trivy_db есть, фикстур нет) — Pii/passwords in tf.
4. **E1 — память:** 482/512 MiB (94%); прогнать scan_project на крупном
   полигоне (>N файлов) и проверить линейность/риск OOM.
5. **E4 — фикстуры в git:** закоммитить артефакты E2E (`requirements.txt`,
   `other-project/`, `.gitignore`, `xss.py` с фиксом, `scripts/`).
6. Перепроверить B2 после фикса T10 (см. T10).

## T15. UX: `rule_id` до 130 символов нечитаем в сводках (низкий, C3)

**Статус:** открыта (низкий приоритет, polish).

`rule_id` вида `opengrep.rb.gems.security.rule-…` длиной до 130 символов
раздувает `top_findings` и ContextPack и плохо читается агентами. Решение:
короткое человекочитаемое имя (`rule_id` → short name) в сводках при
сохранении полного `rule_id/permalink` в машиночитаемых полях. Файлы:
`models/finding.py`, `server.py` (`_build_scan_output`), спека §4.4.

