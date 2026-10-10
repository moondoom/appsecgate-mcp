# AppSecGate MCP — Handoff

## ТЕКУЩАЯ СЕССИЯ: «Docker + Continue MCP» (MCP работает end-to-end ✅)

> Статус: **MCP подключён к Continue через Docker (stdio) и отвечает.**
> Найдены 3 бага рантайма: 1 критичный (gitleaks теряет находки), 2 конфигурационных (semgrep).
> Ниже — что проверено, как воспроизвести и что чинить.

### 0. Окружение (проверено)

- Репо: `/home/animage/projects/appsecgate-mcp`, пакет — `mcp-server/`.
- Docker: client/server 29.8.2, linux/amd64.
- Образ собран в этой сессии: `cd mcp-server && docker build -t appsecgate/mcp:0.1.0 .`
- Контейнер, поднятый Continue: `objective_swanson`
  (mount `/home/animage/projects/appsecgate-mcp -> /workspace:ro`;
  named volumes `appsecgate-cache -> /home/appsecgate/.cache`,
  `appsecgate-data -> /home/appsecgate/.appsecgate-mcp`).
- Сканеры в образе: gitleaks `8.21.2`, trufflehog `3.82.13`, trivy `0.75.0`, semgrep `1.180.0`, git `2.47.3`.

### 1. Конфиг Continue (готов, переносимый)

`.continue/mcpServers/appsecgate.yaml` — stdio через docker, без абсолютных путей:

- `command: docker`
- `cwd: "${workspaceFolder}"` — ключевой момент: относительный путь в args разрешается от cwd
- volume проекта: `"./:/workspace:ro"` (НЕ `${workspaceFolder}:/workspace` — Continue не раскрывает
  переменную прямо в args, передаёт её дословно, и docker ругается на недопустимое имя volume)
- `--network=none`, `--user=1000:1000`, `--read-only`, `--cap-drop=ALL`,
  `--security-opt=no-new-privileges:true`, tmpfs `/tmp`
- `--transport stdio --project /workspace`

**Подтверждено:** `${workspaceFolder}` в `cwd` Continue **подставляет** (проверено через
`docker inspect objective_swanson` -> Source `/home/animage/projects/appsecgate-mcp`).
Гипотеза «stdio не переносим, только streamable-http» — **опровергнута**.

### 2. Что работает ✅

- `session_start` / `scan_file` / `scan_diff` отвечают корректным JSON-RPC.
- `scan_diff` обошёл весь репозиторий; trivy стартует, локальный гейт отрабатывает, ошибок нет.
- Оркестрация, storage (SQLite в `appsecgate-data`), нормализация — без падений.

### 3. Найденные баги

**БАГ 1 (критичный): Gitleaks молча теряет ВСЕ находки.**
Файл `mcp-server/src/appsecgate_mcp/scanners/gitleaks.py`, метод `_norm`:

```python
@staticmethod
def _norm(path: str) -> str:
    return str(Path(path)).lstrip("./")
```

- gitleaks в report даёт **абсолютный** путь `File: "/workspace/x.py"`;
- `_norm` -> `"workspace/x.py"`, а входной файл -> `"x.py"` → фильтр не совпадает;
- `lstrip("./")` срезает любые ведущие `.` и `/` (не префикс) — неверно.

Итог: в режимах `file` и `diff` gitleaks не возвращает ничего никогда.
Воспроизведение: создать файл с `GITHUB_TOKEN = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"` —
gitleaks напрямую находит (RuleID=github-pat), через MCP `scan_file` возвращает `total: 0`.

Фикс — нормализация относительно `project_path`:

```python
def _rel_to_project(self, path: str) -> str:
    p = Path(path)
    if self.project_path and p.is_absolute():
        try:
            return str(p.resolve().relative_to(Path(self.project_path).resolve()))
        except ValueError:
            pass
    return str(p).lstrip("/")
```

Нужен регресс-тест на фильтрацию с абсолютными путями.

**БАГ 2: Semgrep всегда в scanners_skipped.**
Причина: `OSError: [Errno 30] Read-only file system: '/home/appsecgate/.semgrep'`
(`read_only: true`, а semgrep пишет в `$HOME/.semgrep`; writable только `~/.cache` и `~/.appsecgate-mcp`).
`is_available()` -> `semgrep --version` падает -> адаптер выключен.
Проверено: `docker exec -e HOME=/tmp objective_swanson semgrep --version` -> `1.180.0`.
Фикс — writable HOME volume в `.continue/mcpServers/appsecgate.yaml`:

```yaml
      - -v
      - appsecgate-home:/home/appsecgate
```

**БАГ 3: ruleset `p/security-audit` требует сеть при `--network=none`.**
С дефолтным ruleset скан зависает (убит по таймауту 2 мин) — правила тянутся из registry.
Локальный ruleset офлайн работает (проверено `--config /tmp/rule.yaml`).
Варианты: прогреть правила в volume на этапе сборки; убрать `--network=none`; положить
локальный ruleset в образ. В `semgrep.py` уже есть защита от плейсхолдера `requires login`.

### 4. Ложные следы

- `scan_diff -> binary not found: git` **не баг продукта**: следствие вызова `session_start`
  с host-путём вместо `/workspace`. `subprocess.run(cwd=<несуществующий>)` бросает
  `FileNotFoundError`, а `runner.run_subprocess` маскирует его под `binary not found`.
  Стоит улучшить сообщение для cwd-ошибок.
- `docker cp` в контейнер с `read_only: true` -> `container rootfs is marked read-only`;
  писать можно только в `/tmp` (tmpfs) и смонтированные volume.

### 5. Быстрые команды

```bash
# Сборка
cd mcp-server && docker build -t appsecgate/mcp:0.1.0 .

# Интерфейс работающего контейнера Continue
docker inspect objective_swanson --format '{{json .Mounts}}'
docker exec objective_swanson gitleaks version
docker exec -e HOME=/tmp objective_swanson semgrep --version
```

---

## Архив: сессия «тестирование и отладка» — завершена

> Статус: **всё зелёное.** Тесты, линт, entrypoints и Docker-образ проверены.

### Окружение

- Репо: `/home/animage/projects/appsecgate-mcp`, рабочий каталог пакета — `mcp-server/`.
- Python 3.12; `uv` — `~/.local/bin/uv`. Команды из `mcp-server/`:

```bash
cd mcp-server
uv sync --extra dev
uv run pytest -q
uv run ruff check src tests
```

- Docker доступен (server 29.8.2, buildx 0.37.1).

### Итог сессии

**Тесты — 36 passed.** Исправлен `tests/test_git.py`: фикстура `repo` теперь создаёт репозиторий
в подкаталоге `tmp_path/repo` (раньше `git init` делался прямо в `tmp_path`, из-за чего
`tmp_path/nope` оказывался внутри репо и `is_git_repo` возвращал True).

**Линт — All checks passed.** Автофикс `ruff check src tests --fix` закрыл 41 ошибку
(W292/I001/UP017/UP035). Вручную:
- `models/finding.py`: `Severity`/`Category` переведены на `enum.StrEnum` (UP042).
- `orchestration/coordinator.py`: `zip(scanners, results, strict=True)` (B905).

**Entrypoints — работают.** `python -m appsecgate_mcp --help` и `uv run appsecgate-mcp --help` -> OK.
Регистрируются все 11 MCP-tools (8 tools + 3 hook-хендлера).

**Docker — образ собирается и работает.** Исправлено в `Dockerfile`:
1. `readme = "README.md"` в pyproject, но файл не копировался в builder -> фикс
   `COPY pyproject.toml README.md ./`.
2. Пустая строка-продолжение после `RUN uv venv ... && \` — убрана.
3. Gitleaks: asset-суффикс архитектуры `amd64` -> `x64`.
4. Trivy: пин `0.58.1` больше не существует upstream (HTTP 404) -> `0.75.0`.
5. TruffleHog: суффикс `amd64` (корректно), пин `3.82.13` жив.
Заведены ARG: `GITLEAKS_ARCH=x64`, `TRUFFLEHOG_ARCH=amd64`, `TRIVY_ARCH=64bit`.

Проверено в контейнере: сканеры gitleaks `8.21.2`, trufflehog `3.82.13`, trivy `0.75.0`,
semgrep `1.180.0`; `id` -> `uid=1000(appsecgate) gid=1000(appsecgate)`; `session_start()` -> `status: ready`;
`mcp.list_tools()` -> 11 tools.

> Примечание: `trufflehog` отсутствует в дефолтном списке сканеров, потому что в
> `config/default.yaml` категория `secrets` использует `gitleaks`. Это ожидаемо.

### Известные «фантомы» (устранены — не пугаться при grep истории)

- Повреждения файлов прошлых сессий: висячие закрывающие fence в `registry.py`/`stores.py`,
  обрыв тела `_commit` в `db.py` — восстановлены.
- При странных SyntaxError **сначала** проверять файл целиком, а не только место из traceback.

### Осталось на будущее (не блокеры)

- `update_config` при невалидном YAML в `.appsecgate-mcp/config.yaml` молча теряет
  старый конфиг (`except yaml.YAMLError: existing = {}`). Стоит вернуть предупреждение.
- `scan_diff` при пустом diff мутирует `ScanResult().meta` — покрытия нет (тест проходит).
- Hook-контракт (`session_start`/`pre_tool_use`/`post_tool_use`) зарегистрирован как
  MCP-tools; интеграция с реальным клиентом не подтверждена.
- CI: workflow для `pytest`/`ruff`/`docker build` не заведён.