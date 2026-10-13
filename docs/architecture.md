# Архитектура локального сканера AppSecGate MCP

> **Версия:** 1.0 (draft)
> **Статус:** Architecture Design
> **Дата:** 2026-10-09
> **Область:** Фаза 1 — Локальный MCP-сервер

---

## 1. Ключевые архитектурные принципы

Архитектура строится на пяти принципах, которые определяют все решения:

| Принцип | Что означает на практике |
|---------|--------------------------|
| **Non-root by design** | MCP-сервер работает в контейнере от непривилегированного пользователя. Нет `docker.sock`. Нет capabilities. Read-only rootfs. |
| **Warn-only локально** | Локальный контур никогда не блокирует разработчика. Максимум — предупреждение. Блокировка — только в CI. |
| **Журнал показанного** | Каждая показанная находка логируется в `shown_findings.db`. Это данные для будущего CI-контура (`block_on_unresolved_local`). |
| **Офлайн-первый** | Всё работает без master-сервера. Сеть нужна только для обновления баз сканеров. |
| **Изоляция сканеров** | Каждый сканер — отдельный процесс через `subprocess`. Падение одного не роняет остальные. |

---

## 2. Компонентная диаграмма

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        МАШИНА РАЗРАБОТЧИКА (HOST)                        │
│                                                                          │
│  ┌────────────────┐                                                      │
│  │  AI-Агент      │  Claude Code / Cursor / Cline / Continue             │
│  │  (MCP Client)  │                                                      │
│  └───────┬────────┘                                                      │
│          │ MCP Protocol (stdio, HTTP)                                    │
│          │                                                               │
│  ┌───────▼──────────────────────────────────────────────────────────┐   │
│  │                     DOCKER CONTAINER: appsecgate-mcp                 │   │
│  │                     user: 1000:1000, read_only: true              │   │
│  │  ┌────────────────────────────────────────────────────────────┐  │   │
│  │  │                    MCP SERVER LAYER                        │  │   │
│  │  │  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐  │  │   │
│  │  │  │ Tool Router  │  │ Hook Handler │  │ Session Manager │  │  │   │
│  │  │  │  (FastMCP)   │  │ (PostToolUse)│  │ (config, state) │  │  │   │
│  │  │  └──────┬───────┘  └──────┬───────┘  └────────┬────────┘  │  │   │
│  │  └─────────┼─────────────────┼───────────────────┼───────────┘  │   │
│  │            │                 │                   │              │   │
│  │  ┌─────────▼──────────────────────────▼───────────────────┐  │   │
│  │  │                  ORCHESTRATION LAYER                    │  │   │
│  │  │  ┌──────────────────────┐  ┌──────────────┐            │  │   │
│  │  │  │ Scan Coordinator     │  │ Gate Engine  │            │  │   │
│  │  │  │ (parallel run, fix   │  │ (warn/block) │            │  │   │
│  │  │  │  verify)             │  │              │            │  │   │
│  │  │  └────────┬─────────────┘  └──────┬───────┘            │  │   │
│  │  └───────────┼───────────────────────┼────────────────────┘  │   │
│  │              │                       │                        │   │
│  │  ┌───────────▼───────────────────────▼────────────────────┐  │   │
│  │  │                  SCANNER ADAPTER LAYER                    │  │   │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │  │   │
│  │  │  │ Semgrep  │ │ Gitleaks │ │TruffleHog│ │  Trivy fs    │  │  │   │
│  │  │  │ Adapter  │ │ Adapter  │ │ Adapter  │ │  Adapter     │  │  │   │
│  │  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬───────┘  │  │   │
│  │  └───────┼────────────┼────────────┼───────────────┼─────────┘  │   │
│  │          │            │            │               │             │   │
│  │  ┌───────▼────────────▼────────────▼───────────────▼─────────┐  │   │
│  │  │              NORMALIZATION LAYER                            │  │   │
│  │  │  Единый формат Finding + Fingerprint Generator             │  │   │
│  │  └──────────────────────┬─────────────────────────────────────┘  │   │
│  │                         │                                        │   │
│  │  ┌──────────────────────▼─────────────────────────────────────┐  │   │
│  │  │                  STORAGE LAYER (SQLite)                    │  │   │
│  │  │  shown_findings.db │ feedback.db │ scan_cache.db           │  │   │
│  │  └────────────────────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  Bind-mount (ro):          Named volume (rw):                            │
│  • ./project → /workspace  • appsecgate-cache → ~/.cache                    │
│  • ./.appsecgate-mcp → /config                                              │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTPS (опционально, Фаза 2)
                                    ▼
                        ┌───────────────────────┐
                        │   MASTER SERVER       │
                        │   (не в Фазе 1)       │
                        └───────────────────────┘
```

---

## 3. Слои архитектуры

### 3.1. MCP Server Layer

Отвечает за коммуникацию с AI-агентом по протоколу MCP.

| Компонент | Ответственность |
|-----------|-----------------|

| **Tool Router** | Регистрирует MCP-инструменты (`scan_file`, `scan_diff`, `scan_project`, `get_config`, `submit_feedback`, `suppress_finding`, `get_scan_history`). Валидирует входные параметры через Pydantic. |
| **Hook Handler** | Принимает события от AI-агента (`SessionStart`, `PreToolUse`, `PostToolUse`). Триггерит оркестрацию. |
| **Session Manager** | Хранит состояние сессии: активный проект, стек, конфигурацию, флаги (например, «идёт сканирование»). Живёт в памяти процесса. |

**Транспорт**: два режима.

- **stdio** — основной. AI-агент запускает контейнер и общается через stdin/stdout. Просто, безопасно, работает везде.
- **streamable-http (HTTP)** — опциональный. Нужен, если MCP-сервер запущен как долгоживущий демон и обслуживает несколько клиентов. Единая точка входа `POST/GET /mcp`.

> **Примечание.** Старый транспорт **SSE (`/sse` + `/messages/`)** объявлен устаревшим
> (MCP spec 2025-03-26). Он оставлен в CLI как deprecated-алиас и печатает
> `DeprecationWarning`; используйте `--transport streamable-http`.

```python
# Псевдокод регистрации инструментов
from fastmcp import FastMCP

mcp = FastMCP("appsecgate-mcp")

@mcp.tool()
async def scan_diff() -> ScanResult:
    """Сканирует staged + unstaged изменения."""
    files = await git_changed_files()
    return await coordinator.scan(files, mode="diff")

@mcp.tool()
async def scan_file(path: str) -> ScanResult:
    """Сканирует конкретный файл."""
    return await coordinator.scan([path], mode="file")

@mcp.tool()
async def submit_feedback(finding_id: str, type: str, reason: str) -> None:
    """Отправляет обратную связь по находке."""
    await feedback_store.save(finding_id, type, reason)

@mcp.tool()
async def suppress_finding(finding_id: str, reason: str, expires_at: str) -> None:
    """Создаёт локальный suppression."""
    await suppression_store.create(finding_id, reason, expires_at)
```

### 3.2. Orchestration Layer

Мозг системы. Управляет потоком «скан → нормализация → автофикс → показ → логирование».

#### Scan Coordinator

Ключевая задача — **параллельный запуск сканеров** для соблюдения SLA `< 5 сек` на diff.

```python
class ScanCoordinator:
    async def scan(self, files: List[str], mode: str) -> ScanResult:
        # 1. Определяем, какие сканеры применимы к файлам
        tasks = self._plan_scans(files, mode)
        
        # 2. Параллельный запуск (asyncio.gather)
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 3. Нормализация + fingerprinting
        findings = self.normalizer.normalize(raw_results)
        findings = [f.with_fingerprint() for f in findings]
        
        # 4. Дедупликация между сканерами
        findings = self.dedup.deduplicate(findings)
        
        # 5. Применяем локальные suppression
        findings = self.suppression.filter(findings)
        
        # 6. Сортируем по severity
        findings.sort(key=lambda f: SEVERITY_ORDER[f.severity], reverse=True)
        
        return ScanResult(findings=findings, meta=self._meta())
    
    def _plan_scans(self, files, mode):
        """Решает, какие сканеры запускать на какие файлы."""
        plan = []
        by_lang = group_by_language(files)
        
        if "python" in by_lang or "javascript" in by_lang:
            plan.append(self.semgrep.scan(by_lang, mode))
        if mode == "diff" or any(is_secret_candidate(f) for f in files):
            plan.append(self.gitleaks.scan(files, mode))
        if lock_files_present(files):
            plan.append(self.trivy.scan_fs(lock_files(files)))
        return plan
```

**Почему параллельно, а не последовательно**: Semgrep, Gitleaks и Trivy независимы друг от друга и работают с разными типами файлов. При последовательном запуске время суммируется; при параллельном — определяется самым медленным сканером.

#### Gate Engine

Разделяет логику для локального и CI-контура.

```python
class GateEngine:
    def evaluate(self, finding: Finding, context: ScanContext) -> GateDecision:
        config = context.config
        
        if context.mode == "local":
            # Локально — только warn
            if finding.severity in config.gates.local.warn_on:
                return GateDecision(action="warn", reason="local_warn")
            return GateDecision(action="info")
        
        if context.mode == "ci":
            # CI — блокировка по severity
            if finding.severity in config.gates.ci.block_on:
                return GateDecision(action="block", reason="ci_severity")
            
            # Killer-feature: было показано локально и не исправлено
            if config.gates.ci.block_on_unresolved_local:
                if self.shown_store.was_shown(finding.fingerprint):
                    return GateDecision(action="block", reason="unresolved_local")
            
            return GateDecision(action="warn", reason="ci_new")
```

**Ключевая деталь**: `shown_store.was_shown(fingerprint)` — это и есть реализация «ты знал и решил не чинить». Работает только если fingerprint стабилен.

### 3.3. Scanner Adapter Layer

Каждый сканер — изолированный адаптер с единым интерфейсом.

```python
class BaseScanner(ABC):
    name: str
    supported_languages: List[str]
    
    @abstractmethod
    async def scan(self, files: List[str], mode: str) -> List[RawFinding]:
        ...
    
    @abstractmethod
    def is_available(self) -> bool:
        ...
```

| Адаптер | Бинарник | Команда | Особенности |
|---------|----------|---------|-------------|
| **SemgrepAdapter** | `semgrep` | `semgrep --json --config <rulesets> <files>` | Требует скачивания rulesets (кэшируется). Поддерживает `--baseline` для diff-режима. |
| **GitleaksAdapter** | `gitleaks` | `gitleaks detect --no-git --report-format json --source <dir>` | Лучше работает на директории, чем на отдельных файлах. |
| **TruffleHogAdapter** | `trufflehog` | `trufflehog filesystem --json <path>` | Дополняет Gitleaks (разные эвристики). Запускать только если Gitleaks не нашёл — экономия времени. |
| **TrivyAdapter** | `trivy` | `trivy fs --format json --scanners vuln,misconfig,license <path>` | Работает с lock-файлами и IaC. Без `docker.sock`. |

#### SemgrepAdapter — важные детали

Semgrep поддерживает **baseline-режим**, который идеально подходит для diff-сканирования:

```bash
semgrep --json --baseline <commit> --config /opt/appsecgate/rules/opengrep-community .
```

Это позволяет Semgrep самому отфильтровать находки, которые уже были в baseline, и вернуть только новые. Альтернатива — фильтрация на нашей стороне через fingerprint.

#### TrivyAdapter — важные детали

```python
class TrivyAdapter(BaseScanner):
    def __init__(self):
        self.cache_dir = os.environ.get("TRIVY_CACHE_DIR", "/home/appsecgate/.cache/trivy")
    
    async def scan(self, files, mode):
        # Сканируем только релевантные файлы: lock-файлы, *.tf, k8s/*.yaml, Dockerfile
        targets = self._filter_targets(files)
        if not targets:
            return []
        
        cmd = [
            "trivy", "fs",
            "--format", "json",
            "--quiet",
            "--cache-dir", self.cache_dir,
            "--skip-db-update",       # База обновляется отдельно
            "--skip-java-db-update",
            "--scanners", "vuln,misconfig,license",
            "--severity", "CRITICAL,HIGH,MEDIUM",
            *targets,
        ]
        result = await run_subprocess(cmd, timeout=120)
        return self._parse(result.stdout)
```

`--skip-db-update` критичен: без него Trivy будет пытаться обновить базу при каждом скане, что замедлит работу и создаст сетевые вызовы.

### 3.4. Normalization Layer

Приводит вывод всех сканеров к единому формату `Finding`.

```python
@dataclass
class Finding:
    fingerprint: str          # Детерминированный ID
    rule_id: str              # ID правила сканера
    severity: Severity        # CRITICAL | HIGH | MEDIUM | LOW | INFO
    file_path: str            # Относительный путь
    line_start: int
    line_end: int
    message: str
    scanner: str              # semgrep | gitleaks | trufflehog | trivy
    category: str             # sast | secret | sca | iac | license
    metadata: dict            # Специфичное для сканера
    remediation: Optional[str]
```

#### Fingerprint Generator

Самая нетривиальная часть. Fingerprint должен быть **стабилен при сдвигах строк** и **уникален для разных проблем**.

```python
class FingerprintGenerator:
    @staticmethod
    def generate(finding: Finding) -> str:
        # Нормализуем сниппет кода:
        # 1. Убираем пробелы в начале/конце
        # 2. Убираем комментарии
        # 3. Схлопываем множественные пробелы
        normalized = normalize_snippet(finding.snippet)
        
        # Хэш от rule_id + file_path + нормализованный сниппет
        # НЕ включаем номер строки — он может сдвинуться
        key = f"{finding.rule_id}:{finding.file_path}:{normalized}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]
```

**Компромисс**: fingerprint может «схлопнуть» две разные находки одного правила в одном файле, если у них идентичный нормализованный сниппет. Это приемлемо — такие случаи редки, и лучше «схлопнуть», чем «раздвоить» при сдвиге строк.

### 3.5. Storage Layer

Три SQLite-базы. Все — в `~/.appsecgate-mcp/` (внутри контейнера это named volume).

#### `shown_findings.db`

Главная база. Журнал всех находок, показанных разработчику.

```sql
CREATE TABLE shown_findings (
    fingerprint TEXT PRIMARY KEY,
    rule_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    severity TEXT NOT NULL,
    scanner TEXT NOT NULL,
    first_shown_at TIMESTAMP NOT NULL,
    last_shown_at TIMESTAMP NOT NULL,
    show_count INTEGER DEFAULT 1,
    status TEXT NOT NULL,  -- SHOWN | FIXED | SUPPRESSED | IGNORED
    fixed_at TIMESTAMP,
    suppressed_at TIMESTAMP,
    suppress_reason TEXT
);

CREATE INDEX idx_shown_file ON shown_findings(file_path);
CREATE INDEX idx_shown_status ON shown_findings(status);
```

**Зачем нужна**: без неё невозможен `block_on_unresolved_local` в CI. Это данные, которые переживают сессию и синхронизируются с master-сервером в Фазе 2.

#### `feedback.db`

Обратная связь от разработчика. Нужна для офлайн-режима.

```sql
CREATE TABLE feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    feedback_type TEXT NOT NULL,  -- FALSE_POSITIVE | CONFIRMED | WONT_FIX
    reason TEXT,
    created_at TIMESTAMP NOT NULL,
    synced_at TIMESTAMP  -- NULL = ещё не синхронизировано с master
);
```

#### `scan_cache.db`

Кэш результатов сканирования. Позволяет не пересканировать неизменённые файлы.

```sql
CREATE TABLE scan_cache (
    file_hash TEXT NOT NULL,      -- sha256 содержимого файла
    scanner TEXT NOT NULL,
    scanner_version TEXT NOT NULL,
    ruleset_hash TEXT NOT NULL,   -- хэш правил сканера
    result_json TEXT NOT NULL,
    cached_at TIMESTAMP NOT NULL,
    PRIMARY KEY (file_hash, scanner, scanner_version, ruleset_hash)
);
```

**Инвалидация**: кэш валиден, пока не изменился файл, версия сканера или набор правил. Любое изменение — промах, файл пересканируется.

### 3.6. Configuration Layer

Конфигурация читается из `.appsecgate-mcp/config.yaml` (bind-mount `:ro`).

**Приоритет**: 
1. Значения из `config.yaml` в проекте
2. Значения по умолчанию из образа (`/etc/appsecgate/default.yaml`)
3. Переменные окружения (перекрывают всё)

```python
class ConfigLoader:
    def load(self, project_path: str) -> Config:
        default = yaml.safe_load(open("/etc/appsecgate/default.yaml"))
        project = yaml.safe_load(open(f"{project_path}/.appsecgate-mcp/config.yaml"))
        merged = deep_merge(default, project)
        return Config.model_validate(merged)
```

---

## 4. Потоки данных

### 4.1. Поток `scan_diff` — основной сценарий

```
AI-агент          MCP Server       Coordinator      Scanners       Storage
   │                   │                │               │              │
   │── scan_diff() ───▶│                │               │              │
   │                   │── plan() ─────▶│               │              │
   │                   │                │── git diff ──▶│              │
   │                   │                │◀── files ─────│              │
   │                   │                │               │              │
   │                   │                │─ semgrep ────▶│              │
   │                   │                │─ gitleaks ───▶│ (параллельно)│
   │                   │                │─ trivy fs ───▶│              │
   │                   │                │◀─ raw ────────│              │
   │                   │                │               │              │
   │                   │                │─ normalize ──▶│              │
   │                   │                │─ fingerprint ─│              │
   │                   │                │─ dedup ──────▶│              │
   │                   │                │─ suppression ─│              │
   │                   │                │               │              │
   │                   │                │── save shown ▶│─────────────▶│
   │                   │◀─ findings ────│               │              │
   │◀─ result ─────────│                │               │              │
```

**Бюджет времени** (цель — < 5 сек):

| Этап | Время |
|------|-------|
| git diff | ~50 мс |
| Semgrep (diff, cached rules) | ~2–3 сек |
| Gitleaks (diff) | ~1 сек |
| Trivy fs (lock-файлы, cached db) | ~1–2 сек |
| Нормализация + fingerprint | ~100 мс |
| Запись в shown_findings.db | ~50 мс |
| **Итого (параллельно)** | **~3–4 сек** |

### 4.2. Поток `PostToolUse`

```
AI-агент           Hook Handler         Gate Engine
   │                    │                     │
   │── Edit file ──────▶│                     │
   │                    │── scan_file() ──────│
   │                    │                     │
   │                    │◀─ findings ─────────│
   │                    │                     │
   │                    │── log shown_findings│
   │                    │                     │
   │◀─ показать всё ────│                     │
```

**Логика**: 
1. Агент изменил файл → `PostToolUse` сработал.
2. Сканируем только этот файл (быстро).
3. Все находки показываем разработчику и логируем в `shown_findings.db`.
4. Фикс генерирует AI-агент своей LLM через `get_fix_context` + `verify_fix`.

---

## 5. Модель безопасности контейнера

```yaml
services:
  appsecgate-mcp:
    image: appsecgate/mcp:0.1.0
    user: "1000:1000"
    read_only: true
    tmpfs:
      - /tmp:size=100M,mode=1777
    volumes:
      - ${PROJECT_PATH}:/workspace:ro
      - appsecgate-config:/.appsecgate-mcp:ro
      - appsecgate-cache:/home/appsecgate/.cache:rw
    environment:
      - HOME=/home/appsecgate
      - TRIVY_CACHE_DIR=/home/appsecgate/.cache/trivy

    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - DAC_OVERRIDE  # только если нужно читать файлы с ограниченными правами
    network_mode: "none"  # Фаза 1: полностью офлайн
    # network_mode: "bridge"  # если нужно обновлять базы сканеров
```

| Мера | Что защищает |
|------|--------------|
| `user: 1000:1000` | Контейнер не может escalate до root даже при RCE |
| `read_only: true` | Злоумышленник не может записать бэкдор в rootfs |
| `cap_drop: ALL` | Нет `chown`, `setuid`, `net_raw` и прочих capabilities |
| `no-new-privileges` | Бинарники с setuid не могут повысить права |
| Bind-mount `:ro` | Контейнер не может изменить код проекта или конфиг |
| `network_mode: none` | Нет сетевого доступа — нет утечек данных |
| Named volume для кэша | Единственное место для записи, изолировано от хоста |

### Что мы **не** делаем

- ❌ Не монтируем `docker.sock`
- ❌ Не используем `privileged: true`
- ❌ Не даём `--cap-add=SYS_ADMIN`
- ❌ Не работаем от root внутри контейнера
- ❌ Не даём доступ к `/proc`, `/sys` хоста

---

## 6. Обработка ошибок и деградация

Система должна работать, даже если часть сканеров недоступна.

| Ситуация | Поведение |
|----------|-----------|
| Один сканер упал | Остальные продолжают. В результат добавляется `scan_error` с именем сканера. |
| База Trivy устарела (> 7 дней) | Возвращаем предупреждение в `meta.warnings`. Скан продолжается. |
| База Trivy отсутствует | Trivy пропускается. Возвращаем `sca_skipped: true`. |
| Сканер не установлен | Адаптер исключается из плана. Предупреждение в `meta`. |
| Таймаут сканера (120 сек) | Сканер убивается, результат помечается как неполный. |
| Нет прав на чтение файла | Файл пропускается, предупреждение в `meta`. |
| SQLite заблокирована | Retry с exponential backoff (3 попытки). |

**Принцип**: частичный результат лучше, чем ошибка. Разработчик должен получить ответ даже при проблемах с одним из сканеров.

---

## 7. Целевые характеристики

| Характеристика | Значение |
|----------------|----------|
| **Время старта контейнера** | < 1 сек |
| **Скан diff (5 файлов)** | < 5 сек |
| **Скан одного файла** | < 2 сек |
| **Размер образа** | < 500 МБ (multi-stage build) |
| **Потребление RAM (idle)** | < 100 МБ |
| **Потребление RAM (скан)** | < 500 МБ |
| **Размер named volume (кэш)** | до 1 ГБ |

---

## 8. Что входит в Фазу 1, а что нет

### Входит

- ✅ MCP-сервер в Docker с non-root
- ✅ Semgrep, Gitleaks, TruffleHog, Trivy fs
- ✅ Параллельный запуск сканеров
- ✅ Нормализация + fingerprint
- ✅ Три SQLite-базы
- ❌ Auto-fix (не реализовано — фикс генерирует AI-агент своей LLM, см. fix-workflow-design §4.2)
- ✅ Хуки `SessionStart`, `PreToolUse`, `PostToolUse`
- ✅ Офлайн-режим
- ✅ Конфигурация через `config.yaml`

### Не входит (Фаза 2+)

- ❌ Master-сервер и синхронизация
- ❌ CI-контур и двойные gates
- ❌ Сканирование образов
- ❌ RBAC
- ❌ Web UI
- ❌ Интеграция с ASOC
- ❌ ГОСТ-модуль

---

## 8.1. Лицензионная модель

Проект распространяется под MIT, но используемые сканеры и правила имеют разные лицензии. Изоляция и выбор правил определяют, что можно поставлять в образе.

### Компоненты и лицензии

| Компонент | Лицензия | Как используется |
|-----------|----------|------------------|
| AppSecGate MCP (код) | MIT | Собственный код, Python-пакет |
| Semgrep (движок) | LGPL-2.1 | Вызывается как отдельный процесс через `subprocess` |
| Правила `opengrep-community` | MIT / LGPL-3.0 | Вендорятся в `rules/` вместе с текстами лицензий |
| Правила `jetbrains/**` | Commons Clause | **Исключены** из bundle |
| Gitleaks | MIT | Отдельный бинарник, конфиг `rules/gitleaks/` |
| TruffleHog | AGPL-3.0 | Только внешний бинарник, исходники не вендорятся |
| Trivy | Apache-2.0 | Отдельный бинарник; Trivy DB засеивается при сборке |

### Правила изоляции

1. **Процессная изоляция.** Все сканеры запускаются через `subprocess` без shell. Код AppSecGate не линкуется с AGPL-компонентами и не импортирует их, поэтому copyleft не распространяется на MIT-код. Юридическая оценка изоляции — открытый вопрос (см. план, §11.6).
2. **Без вендоринга AGPL-кода.** TruffleHog ставится из официального релиза; в репозиторий и образ попадает только бинарник и конфиг `detectors.yaml`.
3. **Правила — атомарный bundle.** Каждый набор правил сопровождается файлом лицензии и записью в `rules/manifest.yaml` (`license`, `redistribution`, `source`).
4. **Режим распространения** задаётся `rules.distribution_mode`:
   - `mit` — бандлы с `redistribution: restricted` блокируются `LicenseGuard`; сборка предупреждает или падает;
   - `commercial` — допускаются все бандлы, при этом соблюдаются условия их лицензий.
5. **Атрибуция.** Сводка лицензий — `rules/THIRD_PARTY_NOTICES.md`. При изменении состава bundle файл обновляется вместе с `manifest.yaml`.
6. **Отпечаток правил.** `ruleset_hash` учитывает `distribution_mode` и лицензии активных бандлов, поэтому смена режима инвалидирует кэш результатов.

### Данные Trivy

Trivy DB не входит в git-репозиторий. Она скачивается на этапе сборки образа (`trivy --download-db-only`) в `/opt/appsecgate/trivy-db-seed` и копируется в `TRIVY_CACHE_DIR` при первом запуске. Java DB включается build-arg `WITH_JAVA_DB=true`. Это снимает вопрос лицензирования данных с кода проекта.

---

## 9. Открытые вопросы для проработки

1. **Fingerprint**: нужен отдельный спайк. Текущий подход (нормализованный сниппет) может давать ложные схлопывания. Нужно протестировать на реальных данных.
2. **TruffleHog vs Gitleaks**: запускать оба или каскадом? Оба — медленнее, но полнее. Каскад (TruffleHog только если Gitleaks не нашёл) — быстрее, но может пропустить. Решение: оба, но TruffleHog только на diff, не на весь проект.
3. **Semgrep baseline**: использовать `--baseline` или собственную фильтрацию? Baseline проще, но требует доступ к git history. Собственная фильтрация — универсальнее.
5. **Синхронизация `shown_findings.db` с master**: как разрешать конфликты, если один и тот же fingerprint показан на разных машинах?

---

## 10. Итог

Архитектура локального MCP-сервера AppSecGate — это **пять слоёв** (MCP → Orchestration → Scanner Adapters → Normalization → Storage), работающих в **непривилегированном Docker-контейнере** с **read-only bind-mount** проекта. Ключевые инженерные решения:

1. **Параллельный запуск сканеров** — для соблюдения SLA `< 5 сек`.
2. **Fingerprint** — для сопоставления находок между локальным и CI-сканом.
3. **`shown_findings.db`** — журнал показанного, основа для `block_on_unresolved_local`.
4. **Отказ от `docker.sock` и сканирования образов** — ради безопасности и простоты.
5. **Офлайн-первый** — работает без master-сервера, что важно для Фазы 1.

Эта архитектура даёт **безопасный, быстрый и автономный** инструмент, который решает главную задачу Фазы 1: доказать ценность локального скана на своём проекте.

---

> Документ будет обновляться по мере прототипирования. Ключевые открытые вопросы (fingerprint, TruffleHog, LLM) требуют отдельных спайков до начала реализации.