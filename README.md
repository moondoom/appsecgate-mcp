# AppSecGate

**Платформа безопасной разработки для AI-эры**

AppSecGate встраивает безопасность в процесс AI-разработки на всех этапах: от написания кода агентом до релиза. Это не «ещё один сканер», а **оркестратор безопасности**, который работает локально через MCP-сервер, синхронизируется с центральным сервером и интегрируется с ASOC/ASPM, BI и процессами комплаенса.

> Безопасность не должна быть «тормозом». Она должна быть **незаметной для разработчика** и **прозрачной для безопасности**.

---

## Проблема

- **AI-агенты генерируют код быстрее, чем безопасность успевает его проверять.** 40–50% AI-кода содержит уязвимости (Veracode, 2026).
- **Сканеры дают шум, а не сигнал.** AppSec-инженеры тратят до 60% времени на триаж false positive.
- **Локальный и CI-скан не синхронизированы.** Разработчик исправил проблему локально, но ASOC об этом не знает.
- **Комплаенс — это бумажная работа.** Доказательства для ГОСТ Р 56939-2024 и ФСТЭК собираются вручную.

---

## Ключевые концепции

### Три контура безопасности

1. **Локальный контур (MCP + Edge)** — работает на машине разработчика, сканирует изменённые файлы, даёт мгновенную обратную связь и умеет работать офлайн.
2. **Центральный контур (Master Server)** — единый источник правды для команды: синхронизация находок, RBAC, апрувы, аудит и интеграция с ASOC/ASPM.
3. **Аналитический контур (BI + Compliance)** — метрики эффективности, дашборды для CISO и автоматизация комплаенса.

```
Локальный (MCP + Edge) → Центральный (Master Server) → Аналитический (BI + Compliance)
```

### Роли

| Роль | Задача |
|------|--------|
| **Developer** | Пишет код, отвечает за свой диф: сканирование, подавление FP в своих файлах |
| **Lead** | Контролирует уязвимости команды, апрувит дифы, управляет SCA |
| **AppSec** | Видит все находки, проводит sec-review, переопределяет severity |
| **CISO** | Управляет рисками: метрики, отчёты, принятие риска |
| **Admin** | Управляет пользователями, проектами и интеграциями |

### Жизненный цикл находки

```
NEW → TRIAGED → IN_PROGRESS → FIXED_LOCALLY → FIXED_VERIFIED
  │                                │
  ▼                                ▼
SUPPRESSED                      REOPENED
  │
  ▼
WONTFIX (принятие риска)
```

---

## Функциональность по фазам

### Фаза 1. Локальный MCP-сервер (MVP)

Цель — мгновенная обратная связь для разработчика и AI-агента.

- **MCP-инструменты (9):** `scan_file`, `scan_diff`, `scan_project`, `auto_fix`, `get_config`, `update_config`, `submit_feedback`, `get_scan_history`, `suppress_finding`.
- **Хуки для AI-агентов:** не MCP-инструменты, а подкоманда CLI `appsecgate-mcp hook <name>` с `<name>` из `session_start`, `pre_tool_use`, `post_tool_use`. JSON-событие читается из stdin, результат JSON пишется в stdout. Опция `--project <путь>` задаёт корень проекта.
- **Сканеры (реализованы):**
  - SAST: Semgrep
  - Secrets: Gitleaks, TruffleHog
  - SCA: Trivy
- **Запланировано (не реализовано):** Bandit, ESLint (SAST); OSV-Scanner, Dependency-Track (SCA); Checkov, KICS (IaC); OWASP ZAP (DAST).
- **Конфигурация проекта:** `.appsecgate-mcp/config.yaml`.
- **Поддержка агентов:** Claude Code, Cursor, Cline, Continue.

### Фаза 2. Master-сервер

Цель — единый источник правды для команды и синхронизация локальных и CI-сканов.

- Централизованная конфигурация политик и порогов.
- Синхронизация находок со всех машин и CI.
- Детерминированный **Finding Fingerprint** для сопоставления находок.
- **Baseline** для каждой ветки и **Delta API** (только новые проблемы).
- Real-time уведомления через WebSocket.
- Аудит действий.
- Интеграции: GitLab CI/CD, DefectDojo, R-Vision, PT ASM.

### Фаза 3. Разделение на роли (RBAC)

Цель — дать каждой роли свои права и инструменты.

- Матрица прав для Developer, Lead, AppSec, CISO, Admin.
- Workflow апрувов: suppression, diff с новыми находками, принятие риска (WONTFIX).
- Разрешение конфликтов: CI — авторитетный источник, подтверждённая находка важнее suppression.

### Фаза 4. Web-сервер для статистики (BI + MCP)

Цель — прозрачная картина эффективности безопасности.

- Дашборды: Developer, Team, AppSec, Executive, Compliance.
- Метрики:
  - Процессные: TTFF, Local Catch Rate, FPR, Suppression Velocity, Developer NPS, Scan Coverage.
  - Операционные: CI Pipeline Duration, MR Block Rate, Escape Rate, MTTR, Suppression Debt, Top Noisy Rules.
  - Бизнес-метрики: инциденты в production, время простоя, time-to-market, стоимость комплаенса.
- Вариант A: интеграция с Metabase / Grafana / Apache Superset.
- Вариант B: встроенный Web UI (React + TypeScript + Recharts/D3).

### Фаза 5. Экспертная система для РБПО (ГОСТ Р 56939-2024)

Цель — автоматизировать аудит и внедрение процессов безопасной разработки.

- Диагностика по 10 разделам ГОСТ Р 56939 и gap-анализ.
- Управление доказательствами и автоматический сбор из GitLab, Jira, сканеров и ASOC.
- Дашборд готовности к сертификации.
- Генерация пакета документов для аудита (PDF/DOCX).

---

## Дорожная карта

| Фаза | Название | Длительность | Ключевой результат |
|------|----------|--------------|-------------------|
| 1 | Локальный MCP | 2–3 месяца | MCP-сервер, работает офлайн, 5+ пользователей |
| 2 | Master-сервер | 3–4 месяца | REST API, синхронизация, GitLab, DefectDojo |
| 3 | Роли (RBAC) | 2–3 месяца | 5 ролей, апрувы, аудит |
| 4 | Web + BI | 2–3 месяца | 5 дашбордов, метрики, отчёты |
| 5 | РБПО | 4–6 месяцев | Диагностика, доказательства, сертификация |

**Итого:** 13–19 месяцев до полноценной платформы.

---

## Нефункциональные требования

- **Производительность:** локальный скан diff — < 5 сек, CI-скан — < 10 мин, API — < 200 мс (p95).
- **Масштабируемость:** 1000+ разработчиков, 100+ проектов, 1M+ находок.
- **Безопасность:** self-hosted, токены с ограниченным сроком жизни, аудит всех действий, шифрование в покое и при передаче, поддержка локальных LLM.
- **Совместимость:** Linux, macOS, Windows (WSL).

---

## Структура репозитория

```
appsecgate-mcp/
├── README.md                    # Этот документ
├── docs/
│   ├── product-vision.md        # Полное описание продукта
│   ├── roadmap.md               # Дорожная карта
│   ├── architecture.md          # Архитектура
│   └── api/openapi.yaml         # OpenAPI-спека
├── mcp-server/                  # Локальный MCP-сервер
├── master-server/               # Центральный сервер
├── web/                         # Web UI (Фаза 4)
├── config/default.yaml          # Дефолтная конфигурация
├── docker-compose.yml
└── .github/workflows/           # CI
```

---

## Быстрый старт

### Локальный MCP-сервер (Фаза 1)

```bash
# Установка зависимостей (из корня репозитория)
make setup

# Запуск MCP-сервера
cd mcp-server && uv run appsecgate-mcp

# Проверка: линт и тесты
make check
```

Полный список команд: `make help`.

Конфигурация проекта задаётся в файле `.appsecgate-mcp/config.yaml`:

```yaml
version: 1
stack:
  languages: [python, typescript]
  frameworks: [fastapi, react]

scanners:
  sast:
    enabled: true
    tool: semgrep
    rulesets: [p/security-audit, p/python]
  secrets:
    enabled: true
    tool: gitleaks
  sca:
    enabled: true
    tool: trivy
    severity_threshold: HIGH

gates:
  block_on: [CRITICAL, HIGH]
  warn_on: [MEDIUM]
```

---

## Глоссарий

| Термин | Определение |
|--------|-------------|
| **MCP** | Model Context Protocol — протокол для взаимодействия AI-агентов с инструментами |
| **ASOC** | Application Security Orchestration and Correlation |
| **ASPM** | Application Security Posture Management |
| **SAST** | Static Application Security Testing |
| **DAST** | Dynamic Application Security Testing |
| **SCA** | Software Composition Analysis |
| **РБПО** | Разработка безопасного программного обеспечения (ГОСТ Р 56939-2024) |
| **TTFF** | Time to First Feedback |
| **MTTR** | Mean Time to Remediate |
| **FPR** | False Positive Rate |
| **Escape Rate** | Доля проблем, дошедших до production |

---

## Лицензия

См. [LICENSE](LICENSE).

> Полное описание продукта: [docs/product-vision.md](docs/product-vision.md)