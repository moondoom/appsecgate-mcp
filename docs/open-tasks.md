# Открытые задачи Фазы 1

Зафиксировано по итогам проверки состояния Фазы 1 (2026-10-13).
Каждая задача — отдельный этап/PR. Перед реализацией — Plan-мод
(см. AGENTS.md, «Workflow: Plan vs Act»).

---

## T1. Fingerprint «двоит» находки (подтверждено, не исправлено)

- Причина: fingerprint = `sha256(rule_id + file_path + normalize_snippet(snippet))[:16]` —
  `rule_id` входит в ключ; `Deduplicator` схлопывает только по точному `(file_path, line_start)`.
- Дубли видны в ответе скана (`_build_scan_output` → `payload["findings"]`),
  не в `shown_findings` (PK=fingerprint, upsert).
- Источники: Gitleaks vs TruffleHog на одном секрете; пересечения Semgrep-правил
  (разные `rule_id`, строки, сниппеты).
- Сквозная идентичность одной проблемы уже есть — `logical_id`
  (`rule_id + file_path + AST-scope|bucket`, `storage/logical_id.py`), на нём работает `verify_fix`.
- Направление фикса (решает Plan-мод): дедуп вывода по `logical_id` / семейству правил;
  схемы БД и сигнатуры тулов не трогать.

## T2. Инструкция развёртывания для Continue / Cline / Claude Code (отсутствует)

- В репо только `.continue/mcpServers/appsecgate.yaml` (имя сервера `"AppSecGate MCP"`).
  Нет конфигов под Claude Code (`.mcp.json`), Cline (`mcp_settings.json`), Cursor (`.cursor/mcp.json`).
- Инструкция должна содержать: каноническое имя MCP-сервера (определяет префикс тулов
  `mcp__<name>__*`), готовые конфиги под каждый клиент, словарь полей находки
  (`finding_id` = `fingerprint`, `rule_id` = «название проблемы»), шаги проверки и
  диагностики после установки.
- Уточнить у владельца: «корректное название проблемы» — имя сервера в клиенте или
  именование находок (план должен покрыть оба варианта).

## T3. План тестирования MCP на тестовом проекте (отсутствует)

- Есть 283 юнит/интеграционных теста (мок-сканеры, tmp-SQLite); E2E на реальном
  проекте нет. Спека §7.3 требует цикл scan → context → fix → verify.
- План должен включать: проект-полигон с намеренными уязвимостями (секреты,
  инъекции, устаревшие зависимости) и своим `.appsecgate-mcp/config.yaml`;
  сценарии по всей воронке (session_start → scan_file/scan_diff/scan_project →
  query_findings_db → get_fix_context(_batch) → verify_fix(_batch) → suppress →
  feedback → export_snapshot); регресс-тест на «двоение» (T1); NF-замеры (§6.2);
  две параллельные сессии на разных проектах; критерии выхода §7.1–7.2.

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