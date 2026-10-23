# Развёртывание AppSecGate MCP для AI-агентов

Инструкция по подключению сервера к агентам (задача T2, `docs/open-tasks.md`).
Примеры конфигов приведены здесь, в документе; единственный рабочий конфиг —
`.continue/mcpServers/appsecgate.yaml` (каталог `.continue/` в `.gitignore`,
поэтому файл локальный и в репозиторий не попадает).

## 1. Каноническое имя сервера

Имя MCP-сервера определяет префикс тулов в клиенте:

```
mcp__<имя_сервера>__<имя_тула>
```

Каноническое имя — **`appsecgate`** (без пробелов). Тогда:

- `mcp__appsecgate__scan_file`
- `mcp__appsecgate__scan_project`
- `mcp__appsecgate__get_fix_context`
- …и так для всех тулов.

Пробелы и регистр в имени ломают префикс у некоторых клиентов, поэтому в
документации и конфигах используется `appsecgate` без изменений.

## 2. Предусловия

- Docker-образ собран: `make docker-build` (корень репо).
  Опубликованный образ: `moondoom/appsecgate-mcp:0.1.0`.
- Проект, который сканируем, смонтирован в контейнер `:ro`.
- Сеть отключена (`--network=none`) — правила сканеров поставляются локально
  (Rules Bundle), сервер офлайн.
- Для локального запуска без Docker (разработка): `uv run appsecgate-mcp`.

## 3. Общий блок конфигурации

Во всех примерах используется одна и та же docker-команда:

```yaml
# Общая часть (одинакова для всех клиентов)
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
```

Локальный вариант (без Docker, для разработки):

```yaml
type: stdio
command: uv
args:
  - run
  - --directory
  - /абсолютный/путь/к/mcp-server
  - appsecgate-mcp
  - --transport
  - stdio
  - --project
  - /путь/к/проекту
```

> Внимание: локальный запуск НЕ даёт изоляции (read-only, tmpfs, network
> none). Для реального использования собирайте Docker-образ.

## 4. Клиенты

### Continue

Рабочий конфиг — `.continue/mcpServers/appsecgate.yaml` (локальный файл,
`.continue/` в `.gitignore`). Скопируйте его в `<проект>/.continue/mcpServers/`
(или в `~/.continue/mcpServers/`):

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

### Claude Code

Файл конфигурации проекта: `<проект>/.mcp.json` (или командой
`claude mcp add appsecgate -- docker run …`):

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

Cline (v4.x) читает MCP-серверы из **общего** файла настроек
`~/.cline/data/settings/cline_mcp_settings.json` — единый конфиг для CLI,
desktop и VS Code-расширения. Пути `.cline/mcp_settings.json` и
`mcp_settings.json` в корне проекта старые версии Cline больше **не читают**.

Добавьте сервер `appsecgate` в `~/.cline/data/settings/cline_mcp_settings.json`:

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
        "-v", "/абсолютный/путь/к/проекту:/workspace:ro",
        "-v", "appsecgate-cache:/home/appsecgate/.cache",
        "-v", "appsecgate-data:/home/appsecgate/.appsecgate-mcp",
        "moondoom/appsecgate-mcp:0.1.0",
        "--transport", "stdio", "--project", "/workspace"
      ],
      "cwd": "/абсолютный/путь/к/проекту",
      "env": {},
      "disabled": false,
      "timeout": 600
    }
  }
}
```

Важно:

- Для общего (пользовательского) конфига в `-v` и `cwd` указывайте
  **абсолютный путь** к проекту: тогда bind-mount не зависит от того, какой
  воркспейс открыт в Cline в данный момент. Относительный `.:/workspace:ro`
  подходит только для проектного `.mcp.json` (см. ниже).
- `timeout` в Cline задаётся в секундах (600 = 10 мин).
- После изменения перезапустите Cline (или перезагрузите окно VS Code) —
  расширение перечитает файл настроек.
- При первом подключении Cline может запросить подтверждение безопасности —
  подтвердите запуск сервера `appsecgate`.

Альтернатива (только проект): проектный `.mcp.json` в корне воркспейса.
Cline читает его и показывает серверы в отдельной вкладке MCP — каждый сервер
нужно однократно одобрить в интерфейсе. Тот же файл использует Claude Code,
поэтому один `.mcp.json` может обслуживать оба клиента.

### Cursor

Файл: `<проект>/.cursor/mcp.json`:

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

## 5. Словарь полей находки

Сервер возвращает machine-readable находки; «название проблемы» агент
формирует из полей `rule_id` + `message`.

| Поле в ответе | Что это | Пример |
|---------------|---------|--------|
| `finding_id`  | идентификатор находки для `get_fix_context`/`verify_fix`; **равен `fingerprint`** | `9f3a2c88d1b0e4aa` |
| `rule_id`     | имя правила сканера — «название проблемы» (номенклатура у каждого сканера своя) | `aws-access-token` |
| `message`     | человекочитаемое описание от сканера | `AWS Access Key detected` |
| `severity`    | `critical` / `high` / `medium` / `low` / `info` | `high` |
| `category`    | `sast` / `secret` / `sca` / `iac` | `secret` |
| `scanner`     | какой сканер нашёл: `semgrep` / `gitleaks` / `trufflehog` / `trivy` | `gitleaks` |
| `file_path`   | относительный путь от корня проекта | `src/secrets.py` |
| `line_start` / `line_end` | диапазон строк | `12` / `12` |
| `snippet`     | фрагмент кода (redacted, если секрет) | `aws_key = "AKIA…"` |

Рекомендация агенту: в сводных ответах пользователю называть проблему
`rule_id` (+ `message` в скобках), например:
«`aws-access-token` (AWS Access Key detected) в `src/secrets.py:12`».

## 6. Шаги проверки после установки

1. Перезапустить клиент, открыть список MCP-тулов.
2. Убедиться, что видны тулы с префиксом `mcp__appsecgate__`
   (например, `mcp__appsecgate__scan_file`, `mcp__appsecgate__scan_project`).
3. Выполнить `scan_file` по тестовому файлу проекта
   (например, `mcp-server/tests/fixtures/vuln-project/secrets.py`).
4. Ожидаемый ответ: `meta.scanners_ran` непуст, `findings` — список
   находок; в `meta.errors` пусто.
5. `query_findings_db` по `project_id` — записи появляются после скана
   (`shown_findings`).

## 7. Диагностика

| Симптом | Причина | Действие |
|---------|---------|----------|
| Клиент: «не удалось запустить» / пустой ответ | Образ не собран либо имя образа не совпадает | `make docker-build`; сверить тег в конфиге |
| Тулы видны, но ответ — ошибка сети | У проекта слишком большой кэш в `/tmp` (>100M) либо нет прав на bind-mount | Проверить tmpfs и права на каталог |
| Тулы НЕ видны | Неверное имя сервера / префикс | Имя должно быть `appsecgate` (без пробелов); префикс `mcp__appsecgate__` |
| Тулы НЕ видны (Cline) | Сервер не добавлен в `~/.cline/data/settings/cline_mcp_settings.json` (старый путь `.cline/mcp_settings.json` не читается) | Добавить сервер в общий файл и перезапустить Cline/VS Code |
| `scan_file` вернул пустой `findings` | Правила не зарезолвились (офлайн, Rules Bundle пуст) | Проверить `meta.warnings` и `ruleset_hash`; убедиться, что бандл в образе |
| `meta.errors` непуст | Недоступен бинарник сканера (semgrep/gitleaks/trivy) | Проверить образ: `docker run --rm moondoom/appsecgate-mcp semgrep --version` |
| Ошибка «project_id mismatch» | Смена `project_path` в одной сессии | Новый проект = новая сессия (инвариант №6) |