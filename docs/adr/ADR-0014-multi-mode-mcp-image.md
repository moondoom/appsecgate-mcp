# ADR-0014 (обновлённый): Multi-mode MCP image — serve / sync / ci / agent (ro, rw)

**Статус:** Proposed
**Дата:** 2026-11-01
**Файл:** `docs/adr/ADR-0014-multi-mode-mcp-image.md`
**Контекст:** MS-7 завершён. MCP-сервер сканера существует как `appsecgate-mcp` (serve, stdio, `network: none`). `sync` и `ci` реализованы, но требуют унификации упаковки. Агент отсутствует; нужен с **двумя режимами**: `ro` (основной, production-capable, investigation/triage) и `rw` (демонстрация, auto-fix в CI).
**Связанные:** ADR-0003/0006 (CI-контур), ADR-0004 (master, edge, G7), ADR-0008 (agent mode §2.1, classic hard-gate §2.2), ADR-0012/0013 (master — не затрагиваются)
**Не путать с:** ADR-0013 — MCP master (сетевой). Этот ADR — про **MCP сканера** и его режимы.

---

## 1. Контекст

### 1.1. Текущее состояние

```toml
# mcp-server/pyproject.toml
[project.scripts]
appsecgate-mcp = "appsecgate_mcp.server:main"
```

```dockerfile
ENTRYPOINT ["/usr/local/bin/appsecgate-entrypoint.sh", "appsecgate-mcp"]
CMD ["--transport", "stdio"]
```

- **Один entrypoint** `appsecgate-mcp`, default — `serve` (stdio, `network: none`).
- **`sync`** — реализован (MS-3), доступен как подкоманда/флаг (требует проверки).
- **`ci`** — реализован (MS-6, ADR-0006), classic hard-gate, fail-closed exit 2.
- **`agent`** — отсутствует.
- **Entrypoint-обёртка** — уже есть.

### 1.2. Внешние пользователи

**Отсутствуют.** Продукт pre-release. Breaking change допустим без alias.

### 1.3. Ключевые решения этого ADR

1. **Один образ, четыре режима** (`serve`, `sync`, `ci`, `agent`).
2. **`agent` имеет два подрежима:**
   - **`ro` (основной)** — investigation/triage, `:ro`, advisory. **Production-capable.**
   - **`rw` (демонстрация)** — auto-fix, `rw`, demo. Явный opt-in.
3. **Агент сочетает детерминированный анализ и LLM** — фиксируется как архитектурный принцип (§3.5.3).
4. **`serve` и `ci` не меняются по существу** — production-путь стабилен.

---

## 2. Цели и не-цели

### Цели

| # | Цель | Метрика |
|---|------|---------|
| G1 | Один образ, один тег `appsecgate-mcp:latest` | Не `appsecgate-mcp-ci`, не `appsecgate-mcp-agent` |
| G2 | Режимы: `serve`, `sync`, `ci`, `agent` (с подрежимами `ro`/`rw`) | Выбор через `docker run ... <command>` |
| G3 | `serve` — default, максимальная изоляция | `CMD ["serve"]`, `network: none`, `:ro` |
| G4 | `ci` — production hard-gate | `:ro`, fail-closed exit 2, no LLM |
| G5 | **`agent --mode=ro` — основной режим агента** | `:ro`, advisory, production-capable |
| G6 | **`agent --mode=rw` — демонстрация** | `rw`, явный opt-in, не для production |
| G7 | Детерминированный анализ + LLM в агенте | Оба подхода, явно разделены (§3.5.3) |
| G8 | Унификация entrypoint | Один `appsecgate-mcp` с подкомандами |
| G9 | Документация режимов × инвариантов | Таблица в ADR, README, `docs/modes.md` |

### Не-цели

- **Не** production-агент в `rw`. `rw` — только демонстрация/оценка.
- **Не** auto-fix в production CI. `rw` в CI — осознанный demo-сценарий.
- **Не** менять `serve`/`ci` по существу — только упаковка.
- **Не** OAuth/OIDC для LLM. Только OpenAI-compatible с ключом.
- **Не** Anthropic-native API. Только OpenAI-compatible.

---

## 3. Решение

### 3.1. Multi-mode CLI

```toml
[project.scripts]
appsecgate-mcp = "appsecgate_mcp.cli:main"
```

```python
# src/appsecgate_mcp/cli.py
import typer
app = typer.Typer()

@app.command()
def serve(transport: str = "stdio", project: str = "/workspace"):
    """MCP-сервер (stdio, network: none). Default."""

@app.command()
def sync(master_url: str, api_key: str, project: str):
    """Edge-синхронизатор (network: bridge, :ro)."""

@app.command()
def ci(project: str, base_ref: str, master_url: str, api_key: str):
    """Classic hard-gate (network: bridge, :ro, fail-closed)."""

@app.command()
def agent(
    task: str,
    llm_url: str,
    llm_model: str,
    project: str,
    mode: str = "ro",                       # "ro" | "rw"
    master_url: str | None = None,
    api_key: str | None = None,
    no_sync: bool = False,
    output_format: str = "markdown",        # markdown | json | github-pr-comment | gitlab-mr-comment
):
    """Автономный агент. mode=ro — основной (advisory, :ro). mode=rw — демонстрация (:ro→rw)."""
```

```dockerfile
ENTRYPOINT ["/usr/local/bin/appsecgate-entrypoint.sh", "appsecgate-mcp"]
CMD ["serve", "--transport", "stdio"]
```

**Breaking change:** `CMD` меняется с `["--transport", "stdio"]` на `["serve", "--transport", "stdio"]`. Пользователей нет — допустимо.

### 3.2. Режим `serve` — без изменений

Тот же MCP-сервер, stdio, `network: none`, `:ro`. Инварианты №1–5 соблюдены. Default.

### 3.3. Режим `sync` — унификация упаковки

Логика MS-3 не меняется. Подкоманда `appsecgate-mcp sync`. `network: bridge`, `:ro`.

### 3.4. Режим `ci` — унификация упаковки

Логика MS-6 не меняется. Подкоманда `appsecgate-mcp ci`. `network: bridge` (master обязателен), `:ro`, fail-closed exit 2, no LLM. Соответствует ADR-0008 §2.2. Детерминирован.

### 3.5. Режим `agent` — два подрежима

#### 3.5.1. Архитектура

MCP-клиент, спавнящий `serve` как child, общающийся по stdio. LLM-клиент — снаружи.

```text
┌─────────────────────────────────────────────────────────┐
│  Контейнер appsecgate-mcp (mode=agent, network=bridge)  │
│                                                          │
│  ┌────────────────┐        stdio         ┌────────────┐ │
│  │  agent loop    │◀───── MCP protocol ─▶│  serve     │ │
│  │  (MCP client)  │                       │ (child)    │ │
│  │  + LLM client  │──▶ ollama / API       └────────────┘ │
│  │                │──▶ master (sync)                      │
│  └────────────────┘                                       │
└─────────────────────────────────────────────────────────┘
```

#### 3.5.2. Два подрежима

| Подрежим | Project | Что делает | Production | Invariants |
|---|---|---|---|---|
| **`ro`** (default) | `:ro` | Сканирует, триажит, анализирует, предлагает патчи как artifact/PR-comment | ✅ | №1 ✅, №3 ⚠️ (LLM) |
| **`rw`** (opt-in) | `:ro` → `rw` | То же + **применяет** фиксы к коду в CI-пайплайне | ❌ demo | №1 ❌, №3 ⚠️ |

**`ro` — основной режим.** Это advisory-триаж: агент видит находки, анализирует, формирует отчёт/предложения, но **не трогает код**. Инвариант №1 соблюдён. Инвариант №3 ослаблен (агент вызывает LLM), но это **явное свойство режима `agent`**, не `serve`.

**`rw` — демонстрация.** То же + auto-fix в код. Требует явного флага `--mode=rw --i-understand-rw-risk`. В CI — только как демонстрация возможностей, не как production-гейт.

**Ключевое:** `rw` не является «продолжением» `ro` — это отдельный сценарий с явным риском. Документация должна это подчёркивать.

#### 3.5.3. Детерминированный анализ + LLM

**Архитектурный принцип:** агент **сочетает** два подхода, а не выбирает один.

| Подход | Что даёт | Источник |
|---|---|---|
| **Детерминированный** | Воспроизводимость, дешёво, быстро: сканы, fingerprints, gate matrix, config, event-log | MCP-тулы (`scan_project`, `query_findings_db`, `get_config`, `get_fix_context_batch`) |
| **LLM** | Гибкость, семантика, контекст: понимание бизнес-логики, приоритизация, генерация фиксов, объяснение | LLM-клиент (`openai`) |

**Почему оба:**

- **Детерминированный** — источник фактов. Агент не «галлюцинирует» находки; они приходят из сканеров через MCP. Redaction — на приёме (инвариант №4).
- **LLM** — источник интерпретации. Агент объясняет, почему находка критична в контексте проекта, предлагает фикс, приоритизирует.

**Как это работает в цикле:**

```
1. Agent receives the task: triage every current finding.
2. Deterministic inventory:
   - scan_project / scan_diff → complete current findings, not top_findings
   - get_scan_findings → deterministic pages and inventory hash
3. Autonomous LLM analysis:
   - get_fix_context and additional redacted file reads as needed
   - master MCP: similar human-confirmed verdicts and CVE data
   - incremental TP / FALSE_POSITIVE / NEEDS_REVIEW submissions
4. Deterministic controller:
   - pending-ID reminders, duplicate and coverage checks
   - loop detection, checkpoint restart, context compaction and budgets
5. Verdict journal → edge sync → master triage_verdicted events
6. check_gate → Markdown/JSON report
```

The one-shot fixed-context pipeline is replaced by this single autonomous agent; no legacy fixed/free switch is retained (ADR-0015).

**Проектное описание (AGENTS.md, config.yaml):** детерминированная часть контекста. Агент читает `AGENTS.md` (правила проекта) и `config.yaml` (политики) — это **вход** для LLM, не заменяет его. AGENTS.md задаёт **рамки**, LLM действует **внутри рамок**. Это ровно то, что описано в статье: «AGENTS.md + правила, а дальше — на усмотрение модели».

**В ADR фиксируется:** агент **не полагается только на LLM** и **не полагается только на детерминизм**. Оба слоя обязательны. Это архитектурное решение, а не деталь реализации.

#### 3.5.4. LLM-клиент

**`openai` (OpenAI-compatible).** Работает с ollama, vLLM, LM Studio, DeepSeek, OpenAI, Anthropic через прокси. Единый контракт.

**Конфигурация:**

```text
APPSECGATE_LLM_URL=http://ollama:11434/v1
APPSECGATE_LLM_MODEL=qwen3.8:27b
APPSECGATE_LLM_API_KEY=ollama
APPSECGATE_LLM_TIMEOUT=120
```

#### 3.5.5. Output formats

| Format | Назначение | Default |
|---|---|---|
| `markdown` | stdout, человекочитаемый отчёт | ✅ |
| `json` | машиночитаемый, для парсинга | |
| `github-pr-comment` | комментарий в PR (нужен GITHUB_TOKEN) | |
| `gitlab-mr-comment` | комментарий в MR (нужен GITLAB_TOKEN) | |

#### 3.5.6. Лимиты и failure modes

| Параметр | Default | Конфиг |
|---|---|---|
| `max_iterations` | 50 | ✅ |
| `max_tokens` | 500 000 | ✅ |
| `timeout` | 30 мин | ✅ |
| LLM недоступен | **exit 2** (fail-closed) | |
| `max_iterations` достигнут | exit 0 + warning в отчёте | |
| `rw` без `--i-understand-rw-risk` | **exit 2** (защита от случайного auto-fix) | |

### 3.6. Изменение G7 ADR-0004

**G7 ADR-0004:** «`mcp-server/pyproject.toml` не меняется, mcp-server не получает новых production-зависимостей».

**Этот ADR явно изменяет G7:**

- Добавляется `openai` в `mcp-server/pyproject.toml` как **опциональная зависимость**:

```toml
[project.optional-dependencies]
agent = ["openai>=1.0"]
```

- В образе — устанавливается (`pip install .[agent]`). Размер +~2 МБ.
- Если пользователь не использует `agent` — зависимость неактивна в runtime (импорт только в `agent.py`).
- `serve`, `sync`, `ci` — без новых зависимостей.

**Обоснование:** `agent` (в обоих подрежимах) требует LLM-клиента. Свой клиент на stdlib `urllib` (как в ADR-0004 §4.2 для edge) — ~200 строк, tool-calling parsing, streaming — не оправдан, когда `openai` покрывает все OpenAI-compatible провайдеры.

Это **единственное изменение G7**.

### 3.7. Таблица режимов × инвариантов

| Инвариант | `serve` | `sync` | `ci` | `agent --mode=ro` | `agent --mode=rw` |
|---|---|---|---|---|---|
| **№1** проект `:ro` | ✅ | ✅ | ✅ | ✅ | ❌ **`rw`** (demo) |
| **№2** MCP без сети | ✅ | н/п | н/п | ⚠️ child `serve` в сетевом контейнере | ⚠️ то же |
| **№3** сервер не вызывает LLM | ✅ | ✅ | ✅ | ⚠️ ослаблен (LLM) | ⚠️ ослаблен (LLM) |
| **№4** redaction до записи | ✅ | ✅ | ✅ | ✅ (делает `serve`) | ✅ (делает `serve`) |
| **№5** `query_findings_db` SELECT | ✅ | н/п | н/п | ✅ (делает `serve`) | ✅ (делает `serve`) |
| **Детерминизм** | н/п | н/п | ✅ | ❌ advisory | ❌ advisory |
| **Network** | `none` | `bridge` | `bridge` | `bridge` | `bridge` |
| **Production** | ✅ | ✅ | ✅ | ✅ | ❌ demo |
| **Exit codes** | — | 0/2 | **0/1/2** | 0/2 | 0/2 |

**Документация:** эта таблица — в ADR, `README.md`, `docs/modes.md`.

### 3.8. Безопасность `agent`

**`ro` (основной):**

- `:ro` — код не меняется. Инвариант №1 соблюдён.
- Advisory output (Markdown/JSON/PR-comment). Не блокирует PR.
- Sync после работы (опционально, если master задан).
- Prompt injection: данные — untrusted; tool-call'ы из данных не исполняются.
- Логи с redaction.

**`rw` (демонстрация):**

- **Явный opt-in:** `--mode=rw --i-understand-rw-risk`. Без флага — exit 2.
- Пометка в README: «`rw` — experimental, не для production. Используйте `ro` или `ci`».
- Auto-fix применяется к коду — это **осознанный риск**, документирован.
- Sync после работы — аудит на master.
- **Не делаем** (для demo избыточно): двухконтейнерную схему, sandbox для auto-fix, отдельный security review.

**Production-агент в `rw`** (если понадобится) — отдельный ADR с двухконтейнерной схемой (`serve` `:ro` + `agent` `rw`) и security review.

---

## 4. Последствия

### 4.1. Положительные

- **Один образ** для dev, CI, edge, demo. Один тег, один пайплайн.
- **`serve`/`ci` не меняются** — production-путь стабилен.
- **`agent --mode=ro` — production-capable advisory** — не только демонстрация, но и полезный инструмент для триажа в CI.
- **`agent --mode=rw` — демонстрация** возможностей auto-fix.
- **Детерминированный + LLM** — архитектурный принцип, зафиксирован.
- **Таблица инвариантов** — прозрачность.
- **Breaking change допустим** (нет пользователей).

### 4.2. Отрицательные / риски

- **G7 ADR-0004 изменён** (`openai` как опциональная зависимость). Явно.
- **`agent --mode=rw`** — осознанное нарушение №1. Документация критична.
- **`agent --mode=ro`** — ослаблен №3 (LLM). Это свойство режима, не `serve`.
- **`serve` child в `agent`** наследует network namespace — №2 ослаблен.
- **Prompt injection** в `agent` — риск, документирован.
- **Размер образа** +~2 МБ.

### 4.3. Нейтральные

- `sync`/`ci` — логика не меняется.
- REST API master, ADR-0012/0013 — не затрагиваются.

---

## 5. План внедрения

| # | Содержание | Зависит |
|---|---|---|
| **MM-1** | CLI с подкомандами (Typer): `serve`, `sync`, `ci`, `agent` (stub) | — |
| **MM-2** | Перенос `sync` и `ci` под общий entrypoint | MM-1 |
| **MM-3** | `agent --mode=ro`: MCP-клиент (FastMCP Client), spawn `serve` child, LLM-клиент (openai), agent loop, output formats | MM-1 |
| **MM-4** | `agent --mode=rw`: auto-fix + `--i-understand-rw-risk` guard | MM-3 |
| **MM-5** | `openai` в `[project.optional-dependencies] agent`; установка в Dockerfile | MM-3 |
| **MM-6** | System prompt (`prompts/agent_system.md`), AGENTS.md/config как deterministic context, лимиты | MM-3 |
| **MM-7** | Dockerfile: `ENTRYPOINT ["...entrypoint.sh", "appsecgate-mcp"]`, `CMD ["serve", "--transport", "stdio"]` | MM-2 |
| **MM-8** | Документация: `docs/modes.md` (таблица), `README.md` (пометки ro/rw), `docs/ci-integration.md` (примеры) | MM-7 |
| **MM-9** | Тесты: mock LLM, E2E, режимы, guard на `rw` | MM-3..8 |

---

## 6. Тестирование

- **`serve`/`sync`/`ci`:** существующие тесты без регрессий.
- **`agent --mode=ro`:**
  - Mock LLM (FastAPI `/v1/chat/completions`) → агент вызывает MCP-тулы.
  - Цикл завершается по `max_iterations` или отсутствию tool_calls.
  - `:ro` — код не меняется.
  - Sync после работы (если master задан).
  - Output formats: markdown, json.
  - LLM недоступен → exit 2.
- **`agent --mode=rw`:**
  - Без `--i-understand-rw-risk` → exit 2.
  - С флагом → auto-fix применяется.
  - Sync после работы.
- **Prompt injection:** данные с «инструкциями» не приводят к tool-call'ам.
- **AGENTS.md/config как deterministic context:** агент читает и учитывает.
- **Docker:** `docker run appsecgate-mcp:latest` → `serve`; `... ci` → hard-gate; `... agent --mode=ro` → advisory; `... agent --mode=rw --i-understand-rw-risk` → demo.
- `make check` зелёный.

---

## 7. Открытые вопросы

1. **`sync` и `ci` сейчас — подкоманды или отдельные entrypoints?** Требует проверки. Если подкоманды — MM-2 тривиален.
2. **`appsecgate-entrypoint.sh`** — что делает? Учесть при унификации.
3. **Output formats `agent`** — какие в первой итерации? Рекомендация: markdown + json; PR-комментарии — позже.
4. **Мультиагентность** — несколько `agent` параллельно на одном проекте. Рекомендация: нет координации, каждый независим; SQLite WAL справится.
5. **`agent --mode=ro` без master** — допустим (локальный режим, только SQLite + LLM). `--no-sync` или отсутствие `master_url`.
6. **Production-агент в `rw`** — если понадобится, отдельный ADR с двухконтейнерной схемой и security review.
7. **AGENTS.md vs config.yaml** — оба читаются как deterministic context? Или только AGENTS.md? Уточнить в MM-6.

---

## 8. Ссылки

- ADR-0003/0006 (CI-контур, classic hard-gate)
- ADR-0004 (master, edge §4.2, G7)
- ADR-0008 (agent mode §2.1, classic hard-gate §2.2)
- ADR-0012/0013 (master — не затрагиваются)
- `mcp-server/pyproject.toml`, `mcp-server/Dockerfile`
- `docs/architecture.md` §5 (модель безопасности)
- MCP spec 2025-03-26 (stdio, streamable-http)

---

## 9. Итог

- **Один образ `appsecgate-mcp:latest`, режимы:** `serve` (default, `none`, `:ro`), `sync` (edge, `bridge`, `:ro`), `ci` (hard-gate, `bridge`, `:ro`, fail-closed), `agent`.
- **`agent` — два подрежима:**
  - **`ro` (основной)** — investigation/triage, `:ro`, advisory. **Production-capable.**
  - **`rw` (демонстрация)** — auto-fix, `rw`, явный opt-in (`--i-understand-rw-risk`).
- **Агент сочетает детерминированный анализ (MCP-тулы) и LLM** — архитектурный принцип (§3.5.3). AGENTS.md/config — deterministic context; LLM — интерпретация внутри рамок.
- **`serve` и `ci` — production-путь**, инварианты соблюдены. Логика не меняется.
- **`agent --mode=ro`** — ослабляет №3 (LLM), но соблюдает №1 (`:ro`).
- **`agent --mode=rw`** — осознанно нарушает №1 (demo).
- **G7 ADR-0004 изменён:** `openai` как опциональная зависимость (`extras [agent]`).
- **Breaking change допустим** — пользователей нет.
- **Таблица режимов × инвариантов** — обязательный артефакт.
- **Production-агент в `rw`** — отдельный ADR, если понадобится.

---

## 10. Изменения в `docs/adr/README.md`

```markdown
| ADR | Название | Статус |
|---|---|---|
| ADR-0001 | Fingerprint and semantic dedup | Accepted |
| ADR-0003 | CI unresolved local delivery | Paused (superseded in parts by ADR-0006) |
| ADR-0004 | Master server sync | Paused (superseded in parts by ADR-0006); G7 изменён ADR-0014 |
| ADR-0005 | Project reconciliation & shown state machine | Accepted (дополнен ADR-0006) |
| ADR-0006 | Unified finding lifecycle model | Accepted |
| ADR-0007 | Per-branch state | Proposed (Фаза 3) |
| ADR-0008 | Orchestrator presets | Accepted |
| ADR-0012 | Master database and auth foundation | Proposed |
| ADR-0013 | Master MCP interface | Proposed (зависит от ADR-0012) |
| ADR-0014 | Multi-mode MCP image (serve/sync/ci/agent ro+rw) | **Proposed**; изменяет G7 ADR-0004 |
```