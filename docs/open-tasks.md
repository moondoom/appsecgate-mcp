# Открытые задачи Фазы 1

Зафиксировано по итогам проверки состояния Фазы 1 (2026-10-13).
Каждая задача — отдельный этап/PR. Перед реализацией — Plan-мод
(см. AGENTS.md, «Workflow: Plan vs Act»).

**Обновление 2026-10-13:** T1, T2, T3 решены (см. статус под каждой
задачей). T4 остаётся открытой.

---

## T1. Fingerprint «двоит» находки (решено ✅)

**Статус:** реализован второй уровень дедупа — `Deduplicator.deduplicate_families()`
в `coordinator.py`. Ключ: `(file_path, line_start // 20, normalized_body)`, где
body = `metadata.Secret` (для Gitleaks) / сниппет (TruffleHog) или
нормализованный фрагмент (Semgrep). `rule_id` и `scanner` в ключ не входят.
Схемы БД и сигнатуры тулов не тронуты. Пройдено 290 тестов, в том числе
регрессия `test_scan_dedups_same_secret_across_scanners`.

- Причина: fingerprint = `sha256(rule_id + file_path + normalize_snippet(snippet))[:16]` —
  `rule_id` входит в ключ; `Deduplicator` схлопывает только по точному `(file_path, line_start)`.
- Дубли видны в ответе скана (`_build_scan_output` → `payload["findings"]`),
  не в `shown_findings` (PK=fingerprint, upsert).
- Источники: Gitleaks vs TruffleHog на одном секрете; пересечения Semgrep-правил
  (разные `rule_id`, строки, сниппеты).
- Сквозная идентичность одной проблемы уже есть — `logical_id`
  (`rule_id + file_path + AST-scope|bucket`, `storage/logical_id.py`), на нём работает `verify_fix`.
- Направление фикса: механизм уточнён — вместо pure logical_id (включает rule_id,
  не схлопнет разные сканеры) использован расширенный ключ «семьи». Файлы:
  `normalization/dedup.py`, `orchestration/coordinator.py`.

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

**Статус:** создан проект-полигон `mcp-server/tests/fixtures/vuln-project/`
(фиктивные секреты, SQLi, XSS, устаревшие зависимости, конфиг с низкими
порогами). Создан `docs/e2e-test-plan.md` — пошаговый сценарий всей воронки
(session_start → scan_file/scan_diff/scan_project → query_findings_db →
get_fix_context → verify_fix → suppress → feedback → export_snapshot),
регрессия T1, NF-замеры §6.2, две параллельные сессии и критерии выхода §7.1.

- Есть 290 юнит/интеграционных теста (мок-сканеры, tmp-SQLite); E2E на реальном
  проекте — отдельный документ, исполняется вручную.
- План включает: проект-полигон с намеренными уязвимостями, сценарии по всей
  воронке, регресс-тест на «двоение» (T1), NF-замеры, две параллельные
  сессии, критерии выхода.

## T4. Rules Bundle для Semgrep «обрезан» (подтверждено, не исправлено)

- Срез `opengrep-community` включает только `c/`, `csharp/`, `go/`, `javascript/`,
  `python/`, `scala/` + `lgpl/` (js/swift/oc); `jetbrains/` исключён целиком
  (Commons Clause). Источник: `rules/THIRD_PARTY_NOTICES.md`, коммит `9c6d2ea`.
- Фактически нет правил для java, kotlin, ruby, php, rust, typescript, hcl — при
  том что `SemgrepAdapter.supported_languages` заявляет 15 языков, а дефолтный
  `config.rulesets` — `p/security-audit` (шире среза).
- Профильная фильтрация усугубляет: бандл `community-sast` имеет теги
  `["owasp", "generic", "py", "js", "go", "iac"]`, поэтому при профиле на другой
  язык бандл отбрасывается (`_rulesets_for_languages`, safe-fallback к полному набору).
- Fallback `p/security-audit` (когда Rules Bundle не зарезолвился) требует доступа
  к registry semgrep — в офлайне (`network_mode: none`) не работает.
- Направление (решает Plan-мод): расширить срез недостающими языками либо явно
  декларировать фактический охват в конфиге; сверить профильные теги с содержимым
  бандла; проверить поведение fallback без сети.