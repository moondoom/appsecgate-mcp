# AppSecGate MCP

[![Release](https://img.shields.io/github/v/release/moondoom/appsecgate-mcp?label=release)](https://github.com/moondoom/appsecgate-mcp/releases)
[![Docker Pulls](https://img.shields.io/docker/pulls/moondoom/appsecgate-mcp)](https://hub.docker.com/r/moondoom/appsecgate-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Локальный security-сканер для AI-агентов.**

AI-агенты поставляют код быстрее, чем security успевает его проверить. AppSecGate —
MCP-сервер, который сканирует файлы, diff и целые проекты **прямо внутри Claude
Code, Cursor, Cline или Continue** — офлайн, без отправки вашего кода куда-либо.
Находки нормализуются, дедуплицируются по fingerprint, отслеживаются между
сканами и возвращаются агенту как контекст для исправления.

> Security не должно тормозить разработку. Оно должно быть незаметным для
> разработчика и прозрачным для специалиста по безопасности.

**Читайте:** [«Вызываем паранойю у ИИ-агентов: заменит ли MCP AppSec?» (Хабр)](https://habr.com/ru/articles/1099840/)

## Когда использовать / Когда НЕ использовать

**Используйте, если:**

- вы разрабатываете с AI-агентом и хотите сканировать каждый diff до его принятия;
- вам нужно отслеживание находок между сканами с дедупликацией по fingerprint, а не гора отчётов;
- важна работа офлайн: никаких сетевых вызовов, код не покидает машину, а сам сервер не вызывает LLM;
- агент должен получать контекст для исправления находки (`get_fix_context`) и позже проверять исправление (`verify_fix`).

**НЕ используйте, если:**

- вам нужны масштабный GUI-триаж, RBAC, командные дашборды или интеграция с ASOC.
  Локальное сканирование, централизованная policy и классическая блокировка в CI
  уже реализованы; дашборды и интеграция с ASOC — нет.

## Demo

<!-- Demo GIF (установка + сканирование Juice Shop): docs/assets/demo.gif — ещё не записан. -->

## Быстрая установка

Сервер работает в Docker-контейнере. Проект монтируется **только для чтения**
(`:ro`), у контейнера **нет сетевого доступа** (`--network=none`), а сканирование
никогда не пишет в дерево исходников.

```bash
docker pull moondoom/appsecgate-mcp:0.1.0
```

### Claude Code

Добавьте в `<project>/.mcp.json`:

```json
{
  "mcpServers": {
    "appsecgate": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i", "--network=none", "--read-only",
        "--tmpfs=/tmp:size=100M,mode=1777", "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "-v", ".:/workspace:ro",
        "-v", "appsecgate-cache:/home/appsecgate/.cache",
        "-v", "appsecgate-data:/home/appsecgate/.appsecgate-mcp",
        "moondoom/appsecgate-mcp:0.1.0",
        "--transport", "stdio", "--project", "/workspace"
      ]
    }
  }
}
```

Или зарегистрируйте напрямую:

```bash
claude mcp add appsecgate -- docker run --rm -i --network=none --read-only \
  --tmpfs=/tmp:size=100M,mode=1777 --cap-drop=ALL \
  --security-opt=no-new-privileges:true \
  -v .:/workspace:ro \
  -v appsecgate-cache:/home/appsecgate/.cache \
  -v appsecgate-data:/home/appsecgate/.appsecgate-mcp \
  moondoom/appsecgate-mcp:0.1.0 --transport stdio --project /workspace
```

### Cursor

Добавьте в `<project>/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "appsecgate": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i", "--network=none", "--read-only",
        "--tmpfs=/tmp:size=100M,mode=1777", "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "-v", ".:/workspace:ro",
        "-v", "appsecgate-cache:/home/appsecgate/.cache",
        "-v", "appsecgate-data:/home/appsecgate/.appsecgate-mcp",
        "moondoom/appsecgate-mcp:0.1.0",
        "--transport", "stdio", "--project", "/workspace"
      ]
    }
  }
}
```

### Cline

Cline (v4.x) читает MCP-серверы из общего файла настроек
`~/.cline/data/settings/cline_mcp_settings.json`. Добавьте сервер `appsecgate`:

```json
{
  "mcpServers": {
    "appsecgate": {
      "type": "stdio",
      "command": "docker",
      "args": [
        "run", "--rm", "-i", "--network=none", "--read-only",
        "--tmpfs=/tmp:size=100M,mode=1777", "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "-v", "/absolute/path/to/your/project:/workspace:ro",
        "-v", "appsecgate-cache:/home/appsecgate/.cache",
        "-v", "appsecgate-data:/home/appsecgate/.appsecgate-mcp",
        "moondoom/appsecgate-mcp:0.1.0",
        "--transport", "stdio", "--project", "/workspace"
      ],
      "cwd": "/absolute/path/to/your/project",
      "env": {},
      "disabled": false,
      "timeout": 600
    }
  }
}
```

Для общей пользовательской конфигурации укажите **абсолютный** путь к проекту
в `-v` и `cwd`; относительный путь `.:/workspace:ro` работает только в
проектном `.mcp.json`.

### Continue

Добавьте в `<project>/.continue/mcpServers/appsecgate.yaml`:

```yaml
name: appsecgate
version: 0.1.0
schema: v1
mcpServers:
  - name: appsecgate
    type: stdio
    command: docker
    args:
      - run
      - --rm
      - -i
      - --network=none
      - --read-only
      - --tmpfs=/tmp:size=100M,mode=1777
      - --cap-drop=ALL
      - --security-opt=no-new-privileges:true
      - -v
      - .:/workspace:ro
      - -v
      - appsecgate-cache:/home/appsecgate/.cache
      - -v
      - appsecgate-data:/home/appsecgate/.appsecgate-mcp
      - moondoom/appsecgate-mcp:0.1.0
      - --transport
      - stdio
      - --project
      - /workspace
    connectionTimeout: 600000
    requestOptions:
      timeout: 600000
```

**Проверка установки:** перезапустите клиент и выполните `scan_file` для любого
файла; инструменты появятся с префиксом `mcp__appsecgate__`. Полная инструкция,
краевые случаи и диагностика: [docs/deploy-agents.md](docs/deploy-agents.md).

## Режим агента (появится в 0.1.8)

В исходном дереве уже есть read-only agent runner. Он выполняет полный цикл
триажа: `scan_project`/`scan_diff` → сбор контекста для исправления → вердикты,
объяснения и предложения патчей от LLM → `check_gate` → отчёт → опциональная
синхронизация с master. Он не изменяет проект и не применяет патчи.

LLM работает вне MCP-сервера и настраивается через OpenAI-compatible endpoint;
инвариант «ноль LLM-вызовов на сервере» сохраняется.

```bash
appsecgate-mcp agent \
  --mode=ro --scan=full --policy=warn --output-format=markdown \
  --project . \
  --llm-url http://<llm-host>/v1 --llm-model <model>
```

Бенчмарки моделей и агрегированные результаты на 100 репозиториях:
[отчёт TP-0001](experiments/tp-0001/REPORT.md).

## MCP-инструменты (15)

| Инструмент | Что делает |
|------------|------------|
| `scan_file` | Сканирует один файл и возвращает нормализованные находки. |
| `scan_diff` | Сканирует staged + unstaged + untracked изменения в текущем git-репозитории. |
| `scan_project` | Сканирует весь проект без аргументов — отчёт сверки: counts + TOP-10 + requires_confirmation. |
| `check_gate` | Оценивает последнее сканирование по advisory policy и возвращает GateSummary с рекомендуемым действием. |
| `get_fix_context` | Возвращает ContextPack для находки: находка + фрагмент кода + документация правила. |
| `get_fix_context_batch` | Возвращает ContextPack для нескольких находок, до 20. |
| `verify_fix` | Проверяет одну находку: повторно сканирует файл и сопоставляет по logical_id. |
| `verify_fix_batch` | Проверяет до 20 находок; каждый файл сканируется один раз. |
| `query_findings_db` | Выполняет только SELECT по публичным представлениям v_findings, v_summary, v_projects. |
| `export_snapshot` | Экспортирует снимок находок в ndjson (parquet — Фаза 2). |
| `get_config` | Возвращает активную объединённую конфигурацию сессии. |
| `update_config` | Выполняет deep-merge изменений в `.appsecgate-mcp/config.yaml` и перезагружает сессию. |
| `submit_feedback` | Отправляет обратную связь по находке: FALSE_POSITIVE / CONFIRMED / WONT_FIX. |
| `get_scan_history` | Возвращает журнал показанных находок (shown_findings.db) с попытками верификации. |
| `suppress_finding` | Создаёт или удаляет локальное подавление (`action: suppress\|unsuppress`; не влияет на CI gate в Фазе 1). |

## Сканеры (Фаза 1)

| Категория | Сканеры | Примечания |
|-----------|---------|------------|
| SAST | Semgrep | Встроенные офлайн-правила (Rules Bundle), доступ к реестру не нужен |
| Секреты | Gitleaks, TruffleHog | Значения редактируются до сохранения |
| SCA | Trivy | База уязвимостей добавляется при сборке образа |

Каждый сканер запускается отдельным subprocess без shell. В следующих фазах:
Bandit, ESLint (SAST); OSV-Scanner, Dependency-Track (SCA); Checkov, KICS (IaC);
OWASP ZAP (DAST).

## Модель безопасности

- **Проект только для чтения.** Проект монтируется `:ro`; сервер никогда не пишет в исходники.
- **Офлайн по умолчанию.** `network_mode: none` — никаких исходящих сетевых вызовов.
- **Ноль LLM-вызовов.** Исправление генерирует модель вашего агента; сервер передаёт только контекстные данные, не промпты.
- **Редакция секретов до сохранения.** При записи, а не при чтении.
- **Усиленный контейнер.** Non-root UID 1000, read-only rootfs, `cap-drop=ALL`, `no-new-privileges`.

## Конфигурация

Настройки проекта хранятся в `.appsecgate-mcp/config.yaml` и объединяются
(deep-merge) поверх defaults из образа (`/etc/appsecgate/default.yaml`):

```yaml
version: 1
stack:
  languages: [python, typescript]
  frameworks: [fastapi, react]

scanners:
  sast:
    enabled: true
    tool: semgrep
    rulesets: []          # правила Semgrep берутся из локального Rules Bundle
  secrets:
    enabled: true
    tool: gitleaks
  sca:
    enabled: true
    tool: trivy
    severity_threshold: HIGH

gates:
  local:
    warn_on: [CRITICAL, HIGH, MEDIUM]
    block_on: []            # локально никогда не блокируем
  ci:
    block_on: [CRITICAL, HIGH]
    warn_on: [MEDIUM]
    block_on_unresolved_local: true   # «увидели и не исправили» (Фаза 2)
    diff_base_ref: origin/main        # база для `appsecgate ci`
```

### Опционально: пользовательская загрузка правил Semgrep

В образ входят только правила, которые AppSecGate вправе распространять.
Дополнительные правила пользователь скачивает сам в data-dir — не в проект,
образ или встроенный bundle:

```bash
appsecgate-mcp rules list
appsecgate-mcp rules install \
  --source semgrep --source trailofbits --profile agent300 --accept-licenses
```

Вместо профиля можно явно указать `--languages python,javascript,go`.
Профиль `agent300` оставляет Python, JavaScript, TypeScript, Go, Java, Ruby,
PHP и конфигурационные/IaC-правила, исключая остальные языки и тестовые
фикстуры. Сеть использует только эта host-команда; MCP остаётся офлайн.
Пересборка образа не нужна.

Установите `APPSECGATE_RULES_DISTRIBUTION_MODE=commercial` для MCP-контейнера
и смонтируйте `~/.appsecgate-mcp` хоста в `/home/appsecgate/.appsecgate-mcp`.
Для named volume `appsecgate-data` выполните install в отдельном контейнере
с сетью и тем же volume. Режим `commercial` означает ответственность
пользователя за выбранные лицензии, а не коммерческую лицензию AppSecGate.
Официальные правила Semgrep разрешены для внутреннего использования и не
должны распространяться.

Ревизии, хэши, состав и дубликаты записаны в `rules/.external-rules.json`.
Удаление: `appsecgate-mcp rules remove --source semgrep`. Смена набора меняет
результаты сканирования и `ruleset_hash`.

### Опционально: централизованный CI и синхронизация с master

Локальное MCP-сканирование остаётся офлайн и warn-only. Для общих находок,
синхронизации policy и блокирующих проверок в CI используется отдельная схема
master + edge, описанная в [docs/deploy-master.md](docs/deploy-master.md).

## Сборка из исходников

```bash
make setup          # создание uv-окружения
make check          # линтер (ruff) + тесты (pytest)
make docker-build   # сборка moondoom/appsecgate-mcp:0.1.0
```

## Документация

- [Развёртывание для AI-агентов](docs/deploy-agents.md) — все четыре клиента, проверка, диагностика
- [Развёртывание master + edge](docs/deploy-master.md) — master-сервер, синхронизация, CI gate
- [Архитектура](docs/architecture.md)
- [План E2E-тестирования](docs/e2e-test-plan.md)
- [E2E-отчёт](docs/reports/e2e-report-2026-10-30.md)
- [План Stage 2 TP-0001](docs/test-plans/TP-0001-ci-agent-local-llm.md)
- [Отчёт Stage 2 TP-0001](experiments/tp-0001/REPORT.md) — бенчмарки моделей и агрегированные находки
- [Видение продукта](docs/product-vision.md)
- [Открытые задачи](docs/open-tasks.md)
- [Статья на Хабре](https://habr.com/ru/articles/1099840/) — «Вызываем паранойю у ИИ-агентов: заменит ли MCP AppSec?»

## Лицензия

MIT — см. [LICENSE](LICENSE). Встроенные правила сканеров принадлежат третьим
сторонам (см. [third-party notices](mcp-server/rules/THIRD_PARTY_NOTICES.md)).

Английская версия: [README.md](README.md).
