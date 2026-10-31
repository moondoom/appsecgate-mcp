# Открытые задачи Фазы 1

Зафиксировано по итогам проверки состояния Фазы 1 (2026-10-13).
Каждая задача — отдельный этап/PR. Перед реализацией — Plan-мод
(см. AGENTS.md, «Workflow: Plan vs Act»).

**Обновление 2026-10-30 (решения владельца):** T5, T7, T9, T11, T15
решены (см. статусы под задачами); T8 отложена — нужно больше контекста
для решения (announce-семантика scan_project зафиксирована как есть).

**Обновление 2026-10-31 (PR-E):** T8 закрыта — announce-семантика
`scan_project` заменена отчётом ADR-0005 §2.5 (PR-C: no-args, counts +
TOP-10 + `requires_confirmation`, `mark_shown`); reconcile-сценарии
добавлены в E2E-харнесс (итерация 3, `docs/e2e-test-plan.md` §13).

**Обновление 2026-10-13:** T1, T2, T3 решены (см. статус под каждой
задачей). T4 снята по решению владельца — новых правил не добавляем,
фактический охват приведён к срезу бандла (c, csharp, go, javascript,
python, scala, swift) в `SemgrepAdapter.supported_languages`, `_LANG_TAGS`,
`_SUPPORTED_EXTENSIONS`, `default_rulesets`, `config/default.yaml` и
`manifest.yaml`.

**Обновление 2026-10-14:**

По итогам E2E-прогона 17/17 сценариев (итерация 1; итоговый отчёт —
`docs/reports/e2e-report-2026-10-30.md`)
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
агент формирует сводку). Имя сервера — `appsecgate`. README и `mcp-server/README.md` обновлены ссылками.

- Рабочий `.continue/`-конфиг удалён из репозитория (2026-10-30);
  примеры конфигов — в `docs/deploy-agents.md`, не в рабочей директории.
- Инструкция содержит: каноническое имя MCP-сервера, готовые конфиги под
  каждый клиент, словарь полей находки, шаги проверки, диагностику.
- Корректное название проблемы: `rule_id` (+ `message` в скобках) — сервер
  отдаёт machine-readable; агент формирует сводку.

## T3. План тестирования MCP на тестовом проекте (решено ✅)

**Статус:** план создан (`docs/e2e-test-plan.md`), полигон
`mcp-server/tests/fixtures/vuln-project` + `other-project` подготовлены,
E2E **выполнен 2026-10-14 — 17/17 сценариев, 100%**
(итоговый отчёт `docs/reports/e2e-report-2026-10-30.md`). Инструментарий:
`scripts/e2e_measure/` (MCP-клиент, stdio-контейнеры, полный цикл воронки,
NF-замеры, параллельные сессии). Проверены: scan_file/scan_diff/scan_project,
query_findings_db (SELECT + блокировка UPDATE), get_fix_context(+batch),
verify_fix (not_fixed), suppress + rescan, feedback, history, export_snapshot,
две параллельные сессии (независимые project_id). Дедуп T1 подтверждён:
два gitleaks-правила на одной строке → одна находка.

- Критерии выхода §8 плана — все 7 выполнены.
- NF: scan_project 8.2–8.7 c (цель < 30 c); пиковая память контейнера ~482 MiB
  (цель < 512 MiB); SQLite после цикла — строки/размеры в отчёте §4.
- 290 юнит-тестов остаются зелёными (`make check`).

## T5. Redaction gap: `get_fix_context` window содержит сырые секреты (решена ✅)

**Статус:** решена (2026-10-30). Выбран вариант 1: для secret-находок
`_build_window` маскирует строки `line_start..line_end` целиком как
`[REDACTED]`, остальные строки окна прогоняет через `redact_text`
(известные паттерны и high-entropy-токены — `AKIA…`, `wJalr…`, `ghp_…` —
не утекают и в соседних строках). Для не-secret-категорий окно остаётся
сырым кодом проекта (агент и так имеет доступ к ФС).
Файлы: `orchestration/context_builder.py`; тест
`test_context_builder_redacts_secret_window` (`tests/test_context_and_query.py`).

## T6. `update_config` не отклоняет неизвестные поля (закрыта)

**Статус:** закрыта. `extra="forbid"` во всех конфиг-моделях + фильтр env-overrides.

`update_config({"totally_unknown_field": 42})` → `status: updated`:
Pydantic v2 `extra=ignore` (в `Config` нет `extra="forbid"`), поле тихо
дропается при валидации, но записывается в `config.yaml` (пишется merged-dict).
Ошибки **типов** (`timeout_seconds: "abc"`) корректно дают `status: invalid`.

**Решение:** `_StrictModel` (база для всех конфиг-моделей) с
`model_config = ConfigDict(extra="forbid")` — неизвестное поле ломает валидацию
на любом уровне вложенности, а не молча дропается. Дополнительно
`_apply_env_overrides` теперь применяет override только по уже существующим в
данных путям: инфраструктурные переменные (`APPSECGATE_MCP_HOME` → `mcp.home`,
`APPSECGATE_PROJECT_PATH`, `APPSECGATE_LOG_LEVEL`) больше не просачиваются в
конфиг — иначе `extra="forbid"` уронил бы загрузку.

**Проверка:** 5 новых тестов (reject top-level/nested в `update_config` и
`Config.model_validate`, env-override по существующим путям); все 298 тестов
зелёные; `config/default.yaml`, `examples/` и фикстурные конфиги схеме
соответствуют (проверено).

## T7. Скоп suppression: глобальный по fingerprint или проектный? (решена ✅)

**Статус:** решена (2026-10-30). Решение владельца: **нужен `project_id`.**
`suppressions` получает проектную ось — PK становится
`(project_id, fingerprint)`; `SuppressionStore` несёт `project_id`
(как `ShownFindingsStore`); `create/get/delete/list_all/is_suppressed/
filter_active` фильтруют по проекту. Старая схема без `project_id`
пересоздаётся (No-migration). Одинаковый fingerprint в разных проектах
подавляется независимо.
Файлы: `storage/stores/suppression.py`, `server/session.py`; тесты
`tests/test_suppressions.py`.

## T8. `scan_project`: announce-only, но persist пишет в shown_findings (закрыта ✅)

**Статус:** закрыта (2026-10-31). ADR-0005 (PR-A…PR-C) заменил
announce-семантику полной сверкой: `scan_project()` без аргументов возвращает
отчёт §2.5 (counts + TOP-10 + `requires_confirmation`) и помечает TOP-10
`SHOWN` (`mark_shown`, К3). E2E-покрытие — итерация 3
(`scripts/e2e_measure/scenarios/reconcile.py`, `docs/e2e-test-plan.md` §13).

## T9. `project_id` в Docker не зависит от проекта (решена ✅, P0)

**Статус:** решена (2026-10-30). Решение владельца: **используем переданный
алиас либо определяем его через git** (вариант А + Б). Новый приоритет в
`_resolve_project_identity`:

1. явный `project_id` (`APPSECGATE_PROJECT_ID` / `--project-id`) — как есть;
2. явный alias (`APPSECGATE_PROJECT_ALIAS` / `--project-alias`) →
   `project_id = sha256('alias:' + alias)[:16]`;
3. имя git-репозитория (`.git/config`, `origin` URL → последний компонент;
   иначе имя каталога `.git`) → `project_id = sha256('git:' + имя)[:16]`;
   `.git` ищется вверх по дереву — работает и для bind-mount `.:/workspace:ro`;
4. фолбэк: `sha256(realpath(project_path))[:16]` (прежнее поведение).

`project_alias` в Docker теперь = имя host-репозитория, а не `workspace`.
Инвариант №6 (фиксация project_id в сессии) сохранён.

Файлы: `server/session.py` (`_resolve_project_identity`, `_git_identity`,
`_find_git_dir`, `_repo_name_from_git_url`), `server/cli.py`
(`--project-id`/`--project-alias`), тесты `tests/test_project_identity.py`,
документация `docs/deploy-agents.md`, `docs/architecture.md` §1.

## T10. Недетерминированный дедуп → нестабильные fingerprint (P0, B1/OBS-5)

**Дизайн:** [ADR-0001](adr/ADR-0001-fingerprint-and-semantic-dedup.md).

**Статус:** решено ✅ (2026-10-30) по ADR-0001 §3.2. `Deduplicator._collapse()`
сортирует находки по стабильному ключу
`(-severity_rank, SCANNER_PRIORITY, RULE_PRIORITY, rule_id)` перед выбором
«выжившего»; порядок поступления raw-находок больше не влияет на winner.
Регресс: `TestDeduplicator::test_scanner_priority_independent_of_input_order`,
`TestDeduplicator::test_rule_priority_independent_of_input_order`,
`test_scan_fingerprints_stable_across_runs` (два скана → идентичный fingerprint).
Файлы: `normalization/dedup.py`. Связанная B2 («5 строк при 4 находках») —
перепроверить при T14 (вторая итерация E2E).

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

## T11. `update_config` пишет в проект: конфликт с `:ro` и инвариантом №1 (решена ✅, P1)

**Статус:** решена (2026-10-30). Решение владельца: **проверяем запись и даём
рекомендацию, что пользователь может поменять настройки самостоятельно** —
агент не должен подумать, что это проблема. В каноническом деплое (проект
`:ro`) `update_config` НЕ пишет в проект (инвариант №1) и возвращает
не-ошибку:

- `status: readonly` + `applied: false` + `config_path`;
- `reason`: «project is mounted read-only … expected in the canonical Docker
  deployment, not an error»;
- `how_to_change`: изменить настройки может пользователь — отредактировать
  `.appsecgate-mcp/config.yaml` в host-проекте, смонтировать проект `rw`
  (только для локального dev-запуска) или задать `APPSECGATE_*` env.

Проверка — `os.access(project_path, W_OK)` (без реальной записи в проект).
На rw-проектах поведение не меняется (валидация → атомарная запись → reload).
Файлы: `server/tools/config.py`; тест `test_update_config_readonly_returns_recommendation`.

## T12. `verify_fix`: двойная семантика `status` и `verified_status` (закрыта)

**Статус:** закрыта (2026-10-30, итерация 2 E2E).

Ответ `verify_fix`: `"status": "ok"` (транспортный) +
`"verified_status": "fixed|not_fixed|wont_fix"` (результат верификации).
E2E-харнесс изначально читал только `status` и пропускал результат —
риск для LLM-агентов. Решение: **явная документированная иерархия**
(смена сигнатуры тула запрещена AGENTS.md без явного указания).

Зафиксированный контракт:
- `status` — транспортный статус операции (`ok` | `error`), общий для всех
  MCP-тулов. `ok` НЕ означает «фикс подтверждён».
- `verified_status` — канонический результат верификации
  (`fixed` | `not_fixed` | `wont_fix`). Агенты обязаны читать именно его.
- `verified` — `reported_status == verified_status`; `verified=true` при
  `not_fixed` значит «находка на месте, заявка подтверждена пересканом» —
  не «фикс верифицирован».

Контракт внесён: докстринги `verify_fix`/`verify_fix_batch` (`server.py`),
спека §4.6, тесты `test_verify_fix_response_contract` +
`test_verify_fix_batch_response_contract` (`tests/test_fix_verify.py`).
E2E-харнесс (`scripts/e2e_measure/`) читает `verified_status` с 2026-10-14.

## T13. SCA: 19 CVE схлопнуты в 1 находку (закрыта)

**Дизайн:** [ADR-0001](adr/ADR-0001-fingerprint-and-semantic-dedup.md).

**Статус:** закрыта. Корневая причина — уровень 1 дедупа схлопывал все
находки одного файла с одинаковым `line_start`, а Trivy не проставляет
номера строк для CVE (у всех `line_start=1`). Решение: уровень 1 схлопывает
только кросс-сканерные дубликаты (`dedup.deduplicate`), «семьи» одного
сканера склеивает уровень 2 по телу проблемы. Выбран вариант «перечислять
все CVE» (вместо агрегации по пакету из ADR-0001 §8.4): каждая CVE —
отдельная находка с собственным `rule_id`, видна в `verify_fix`,
`export_snapshot`, `query_findings_db`; в БД конфликтов нет, т.к.
`logical_id` включает `rule_id`.
Файлы: `normalization/dedup.py`, тесты `test_normalization.py`,
`test_coordinator.py`, `docs/e2e-test-plan.md`.

## T14. Вторая итерация E2E: staged-diff, verify_fix-fixed, IaC, память (закрыта)

**Статус:** закрыта (2026-10-30). Отчёт: `docs/reports/e2e-report-2026-10-30.md` —
**28/28 PASS (100%)** на финальном прогоне.

1. **B5 — staged-покрытие:** `run_git_diff_scenarios` — staged + unstaged +
   untracked в одном `scan_diff` (3 файла), граница clean-tree после коммита
   (0 находок), staged-регрессия против старого коммита (`git revert` +
   `git reset --soft` → 1 находка). Попутно исправлен **OBS-8**: deleted-файлы
   из diff передавались сканерам → semgrep терял весь пакет SAST
   (`orchestration/coordinator.py`, фильтр несуществующих файлов).
2. **verify_fix:** wont_fix (note, без перескана) + fixed (реальная правка
   файла на rw-копии полигона) + `verify_fix_batch [fixed, not_fixed]` — все PASS.
3. **D4 — IaC-фикстуры:** добавлен `vuln-project/main.tf` (public S3 ACL,
   IAM full access, RDS password) → `scan_file main.tf` = 3 находки
   (`hashicorp-tf-password`, `AWS-0080`, `AWS-0086`). Попутно исправлен **OBS-7**:
   gitleaks не клал `metadata.Secret` + github-pat обрезает Secret → T1-дедуп
   не схлопывал дубль на одной строке (`scanners/gitleaks.py`,
   `normalization/dedup.py` — канонизация секрета префиксом 40).
4. **E1 — память:** крупный полигон (124 py-файла) под `--memory=512m` →
   144 находки, peak **455.8 MiB**, без OOM. Dockerfile-фикс **OBS-6**:
   strip `*.dist-info` ломал semgrep (StopIteration в opentelemetry.context),
   все SAST-сканы молча давали 0; добавлен setuptools в venv + усилен
   smoke-тест сборки.
5. **E4 — фикстуры в git:** `requirements.txt`, `other-project/`, `.gitignore`,
   `xss.py`, `main.tf`, `scripts/e2e_measure/` — в git (часть в коммите
   T3/96e3625; `main.tf` — в этом коммите).
6. **B2 после фикса T10:** `dedup_stability_recheck` — два скана secrets.py →
   идентичный fingerprint `[0691d13f93462eba]`, PASS.

Файлы: `scripts/e2e_measure/`, `mcp-server/tests/fixtures/vuln-project/main.tf`,
`mcp-server/src/appsecgate_mcp/{orchestration/coordinator.py,scanners/gitleaks.py,
normalization/dedup.py}`, `mcp-server/Dockerfile`, `docs/e2e-test-plan.md` §12,
`docs/reports/e2e-report-2026-10-30.md`.

## T15. UX: `rule_id` до 130 символов нечитаем в сводках (решена ✅, низкий, C3)

**Статус:** решена (2026-10-30).

Короткое человекочитаемое имя (`Finding.short_rule_id()` — последний сегмент
`rule_id` после последней точки: `opengrep.rb.gems.security.rule-…` →
`rule-…`) добавлено в сводки при сохранении полного `rule_id` в
машиночитаемых полях:

- `_build_scan_output` — каждая находка получает доп. поле `"rule"` (полный
  `rule_id` остаётся в `model_dump`);
- `_build_announce_output` — `top_findings` получают `"rule"`.

Файлы: `models/finding.py`, `server/output.py`; тесты
`test_build_scan_output_carries_short_rule_id` и обновлённый
`test_build_announce_output` (`tests/test_context_and_query.py`).


---

# Фаза 2, этап 1 — CI-контур и двойные gates (ADR-0003)

**Дизайн:** [ADR-0003](adr/ADR-0003-ci-unresolved-local-delivery.md)
(Accepted, 2026-10-30). Один этап — один PR. Вне этапа: master-сервер и
синхронизация (`docs/architecture.md` §9.5).

| # | Содержание | Статус |
|---|---|---|
| CI-1 | Принятие ADR-0003, обновление `docs/adr/README.md`, `docs/architecture.md` §8 | ✅ решено |
| CI-2 | CLI `appsecgate ci`: diff против base-ref (`git.py`), exit 0/1/2, `--format text\|ndjson` | ✅ решено |
| CI-3 | shown-source абстракция: snapshot-парсер + подключение к `GateEngine` | ✅ решено |
| CI-4 | Suppression/verify_fix в CI по таблице §5.2 (snapshot-поля) | ✅ решено |
| CI-5 | Конфиг `gates.ci.diff_base_ref` + env override | ✅ решено |
| CI-6 | Пример `.github/workflows/appsecgate-ci.yml` + README + `deploy-agents.md` | ✅ решено |
| CI-7 | Тесты: `test_gate`, `test_shown_source`, `test_git`, `test_ci_cli`; `make check` зелёный | ✅ решено |

Файлы: `orchestration/{ci.py,shown_source.py,gate.py}`, `server/ci.py`,
`server/cli.py`, `git.py`, `config/models.py`, `config/default.yaml`,
`tests/test_ci_cli.py`, `tests/test_shown_source.py`,
`docs/adr/ADR-0003-ci-unresolved-local-delivery.md`.

Осталось на будущее (следующие этапы Фазы 2, вне этого PR):
- E2E CI-полигон по мотивам T14 (фиктивный PR → блокировка/пропуск).

---

# Фаза 2, этап 2 — Центральный (master) сервер (ADR-0004)

**Дизайн:** [ADR-0004](adr/ADR-0004-master-server-sync.md) (Proposed,
2026-10-30). MS-1 = принятие ADR (этот пункт). Статусы этапов заполняются по
мере реализации. Инвариант №2 не пересматривается: сеть — только у
edge-процесса на хосте, MCP-сервер остаётся `network_mode: none`.

| # | Содержание | Статус |
|---|---|---|
| MS-1 | Принятие ADR-0004 + обновление `docs/adr/README.md`, `docs/architecture.md` §8/§9.5 | ✅ решено |
| MS-2 | Схема master-БД + события/агрегаты/аудит; unit-тесты агрегата (§5.3) | ✅ решено |
| MS-3 | Edge `appsecgate-mcp sync`: экспорт локальных БД → события, outbox, idempotent push (urllib) | ✅ решено |
| MS-4 | Master REST API (FastAPI): `/v1/events|findings|suppressions|config|audit`, `/healthz` | ✅ решено |
| MS-5 | Pull вниз: CI/global suppressions + политики применяются локально (§4.6) | ✅ решено |
| MS-6 | CI-источник: `appsecgate ci` всегда тянет показанное с master (snapshot удалён); контрактные тесты | 🚧 в работе (2026-10-31) |
| MS-7 | Docker Compose (master + edge), документация развёртывания | ⬜ не начато |
| MS-8 | DefectDojo/ASOC экспорт (vision §5.2.4) — после MS-7 | ⏸ отложено — вне плана, вернуть при актуализации vision |

**MS-2 (2026-10-31):** создан пакет `appsecgate-master/` (Python ≥ 3.12,
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

**MS-3 (2026-10-31):** edge-подкоманда `appsecgate-mcp sync` (ADR-0004 §4.2,
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

**MS-5 (2026-10-31):** обычный `appsecgate-mcp sync` после push скачивает
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

