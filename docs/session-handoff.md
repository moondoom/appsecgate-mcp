# Дизайн v1: хранение и публикация правил сканеров

> **Принцип v1:** каждое новое механизм — потенциальный источник нестабильности. Правила — это данные. Всё, что решается файлом и конвенцией, решается файлом и конвенцией. Магия добавляется только там, где без неё действительно больно.

---

## 0. Ключевая идея: «Rules Bundle» + резолвер + лицензионный слой

Правила у Semgrep/Gitleaks/TruffleHog живут в разных форматах, у Trivy правил-файлов нет вообще. Объединяем их в один абстрактный слой:

- **Bundle** — версионированный набор файлов правил + `manifest.yaml` с индексами, хэшами и **лицензионными метаданными**.
- **RuleResolver** — слой между `ConfigLoader` и `ScannerRegistry`: превращает логические ID из `config.yaml` в конкретные пути на диске и инвентаризационный хэш.
- **LicenseGuard** — валидатор совместимости лицензий с режимом поставки (`distribution_mode: mit | commercial`).

Это закрывает четыре задачи: офлайн-работа, воспроизводимость, публикация и лицензионная чистота.

**Чего в v1 нет:** файловых watcher'ов, автоопределения сети, deep-merge правил, автоопределения языков, UI для редактирования, hot-reload.

---

## 1. Собственная дефолтная база правил

### 1.1. Лицензионная модель

Проект под **MIT** — permissive-лицензия, совместимая с AGPL/GPL/LGPL при изоляции копилефт-компонентов как внешних процессов. Три правила:

1. **Правила Semgrep** — только под MIT / Apache-2.0 / LGPL-3.0 (без Commons Clause).
2. **TruffleHog** (AGPL-3.0) — только как **немодифицированный внешний бинарник** через `subprocess`. Исходники не вендорим, патчи не накладываем.
3. **Gitleaks** (MIT) и **Trivy DB** (Apache-2.0) — без ограничений.

### 1.2. Источники правил

| Сканер | Источник | Лицензия |
|---|---|---|
| Semgrep | **`qodana/opengrep-sast-rules`** (кроме `jetbrains/**`) | MIT + LGPL-3.0 |
| Semgrep (доп.) | **greprules.io** (опционально) | Apache-2.0 |
| Gitleaks | Встроенный `default.toml` + собственные | MIT |
| TruffleHog | Только `detectors.yaml` | N/A (config) |
| Trivy | `trivy-db` (seed в образе) | Apache-2.0 |

**Почему не `semgrep/semgrep-rules`:** проприетарная Semgrep Rules License v.1.0, запрещает распространение и использование в конкурирующих продуктах.

**Почему не `jetbrains/**`:** LGPL-3.0 **+ Commons Clause**, запрещает коммерческую продажу.

### 1.3. Layout в репозитории

```
mcp-server/rules/
  manifest.yaml              # id, version, path, license, source, tags
  opengrep-community/        # вендоренный срез (без jetbrains/)
    c/  go/  python/  javascript/  iac/
    LICENSE-MIT
    LICENSE-LGPL-3.0
  semgrep-custom/            # собственные правила под MIT
    appsecgate-base.yaml
    appsecgate-secrets.yaml
  gitleaks/
    default.toml
    allowlist.toml
  trufflehog/
    detectors.yaml
  THIRD_PARTY_NOTICES.md
```

В образе (read-only rootfs): `/opt/appsecgate/rules/`.

### 1.4. `manifest.yaml`

```yaml
version: "1.0.0"
distribution_mode: "mit"

bundles:
  - id: "appsecgate/community-sast"
    scanner: "semgrep"
    path: "/opt/appsecgate/rules/opengrep-community"
    license: "MIT AND LGPL-3.0-only"
    source: "https://github.com/qodana/opengrep-sast-rules"
    redistribution: "allowed"
    tags: ["owasp", "generic", "py", "js", "go", "iac"]

  - id: "appsecgate/base"
    scanner: "semgrep"
    path: "/opt/appsecgate/rules/semgrep-custom"
    license: "MIT"
    source: "internal"
    redistribution: "allowed"
    tags: ["appsecgate", "custom"]

  - id: "appsecgate/secrets"
    scanner: "gitleaks"
    path: "/opt/appsecgate/rules/gitleaks"
    license: "MIT"
    source: "internal + gitleaks default"
    redistribution: "allowed"
    tags: ["secrets"]

  - id: "appsecgate/trufflehog-custom"
    scanner: "trufflehog"
    path: "/opt/appsecgate/rules/trufflehog"
    license: "N/A (config only)"
    source: "internal"
    redistribution: "allowed"
    min_scanner_version: "3.82.0"
    tags: ["secrets"]
```

Поле `redistribution`: `allowed | restricted | internal`. `LicenseGuard` при `distribution_mode: mit` блокирует `restricted`.

### 1.5. Привязка к коду

- `SemgrepAdapter.default_rulesets` → `("/opt/appsecgate/rules/opengrep-community", "/opt/appsecgate/rules/semgrep-custom")`.
- `GitleaksAdapter` / `TruffleHogAdapter` получают параметр `rules_path`.
- `scan_cache.ruleset_hash = sha256(manifest.version + sorted(file_sha256) + scanner_version + distribution_mode)`.

---

## 2. Режимы запуска: офлайн по умолчанию

### 2.1. Ключевое решение: **не детектировать сеть автоматически**

Автодетект сети — ловушка: DNS работает, а registry нет; сеть есть, но медленная; в облаке трафик платный; «иногда синхронизируется, иногда нет» — худший тип бага.

### 2.2. Конфигурация

```yaml
network:
  mode: offline        # offline | online — по умолчанию offline
  sync:
    trivy_db: true
    timeout_seconds: 30
    max_db_age_days: 30
```

`offline` — по умолчанию. Единственный режим, гарантирующий воспроизводимость.

### 2.3. Проблема устаревания Trivy DB

**Не «раз в месяц новый контейнер» и не автодетект, а seed + проверка возраста + warning.**

1. `Dockerfile`: `trivy --download-db-only` на этапе сборки.
2. `session_start`: читаем `metadata.json.NextUpdate`.
3. Возраст < N дней → работаем молча. Возраст ≥ N → `meta.warnings`.
4. Если `network.mode: online` — синхронизация с таймаутом и fallback на локальную БД.

**Что в `meta.warnings`:**
```
Trivy DB version: 2024-09-15 (age: 47 days, threshold: 30)
Action: set network.mode=online or rebuild container
```

**Java DB** — не в образе по умолчанию (сотни МБ). Warning `trivy_java_db_missing`. Включается build-arg `WITH_JAVA_DB=true`.

### 2.4. Онлайн-синхронизация

Один раз на `session_start`, **не на каждый скан**. Таймаут обязателен. При таймауте — локальные данные + warning, **без падения**.

---

## 3. Редактирование правил SAST / Secret

### 3.1. Уровень 1: файловые оверрайды (единственный в v1)

```
/opt/appsecgate/rules/                    # дефолт из образа (ro)
<project>/.appsecgate-mcp/rules/          # проектный оверрайд (bind ro)
~/.appsecgate-mcp/rules/                  # пользовательский (writable)
```

**Правила слияния — без deep-merge:**

1. **По имени файла.** Overlay-файл с тем же именем **полностью заменяет** дефолтный.
2. **По директории.** Новая директория — добавляется.
3. **По `manifest.yaml`.** В overlay можно указать `disable: [rule-id]` и `replace: {rule-id: path}`.

Правило — атомарная единица. Заменяем целиком или не трогаем.

**Пример:**

```yaml
# ~/.appsecgate-mcp/rules/manifest.yaml
overrides:
  semgrep:
    disable:
      - "python.lang.security.audit.exec-use"
    replace:
      "python.lang.security.audit.subprocess-shell-true": "~/.appsecgate-mcp/rules/my-subprocess.yaml"
```

### 3.2. Что НЕ делать в v1

- ❌ MCP-инструменты `update_rule` / `reload_rules` — v1.5.
- ❌ UI для редактирования — отдельный продукт.
- ❌ Hot-reload через файловый watcher.
- ❌ Версионирование отдельных правил.
- ❌ Наследование через `extends`.

### 3.3. Flow на `session_start`

1. `ConfigLoader.load()` → `RuleResolver.resolve(config)` → пути + активные бандлы.
2. `LicenseGuard.check(bundles, distribution_mode)`.
3. Валидация per-scanner: `semgrep --validate`, TOML-парс, schema-check.
4. `ruleset_hash` включает `distribution_mode` и список лицензий.
5. **Fail-soft:** невалидный overlay → откат на дефолт + `meta.warnings`, без падения.

---

## 4. Внутренний пайплайн актуализации правил

### 4.1. Принцип: правила живут в git, релиз — это тег

```
[Upstream update detected]
    ↓
[PR в rules-repo]
    ↓
[CI: semgrep --test, --validate, schema-check]
    ↓
[CI: LicenseGuard]
    ↓
[CI: прогон на эталонных проектах]
    ↓
[Merge → tag rules-vX.Y.Z]
    ↓
[Сборка прод-образа]
```

### 4.2. Что проверять в CI

| Шаг | Инструмент | Что ловит |
|---|---|---|
| Синтаксис | `semgrep --validate` | битые YAML |
| Тесты | `semgrep --test` | правила без матчей |
| Gitleaks | dry-run | битый TOML |
| TruffleHog | schema-check | несовместимость с версией |
| Лицензии | `LicenseGuard` | `restricted` в MIT-сборке |
| Размер | `du -sh` | превышение лимита образа |
| Регрессия | 3–5 эталонных проектов | новые FP |

### 4.3. Частота

- `opengrep-sast-rules` — раз в 1–2 месяца.
- Собственные правила — по мере появления паттернов.
- Gitleaks — при обновлении движка.
- Trivy DB — на каждой сборке образа.

**Bundle — стабильная единица. Релиз раз в месяц — оптимальный ритм.**

### 4.4. Что показывать в `meta`

```json
{
  "ruleset_version": "1.4.2",
  "ruleset_hash": "sha256:...",
  "bundles": [
    {"id": "appsecgate/community-sast", "rules_count": 847}
  ],
  "trivy_db": {"version": "2024-10-01", "age_days": 9},
  "warnings": []
}
```

---

## 5. Кэш Trivy DB в образе

**Seed-on-first-run, не «база внутри rootfs».**

- `docker build`: `trivy --download-db-only --cache-dir /opt/appsecgate/trivy-db-seed`.
- `entrypoint`: если `$TRIVY_CACHE_DIR/db/trivy.db` нет → `cp -r seed → $TRIVY_CACHE_DIR`. Named volume writable, rootfs ro.
- `metadata.json.NextUpdate` → warning при устаревании.
- **Лицензионный нюанс:** seed-on-first-run снимает вопрос о лицензировании данных — пользователь получает БД напрямую от Aqua, не в составе вашего образа.

---

## 6. Оптимизация SAST «под подпроект»: **не делать в v1**

### 6.1. Почему автоопределение — ловушка

- Определение языка по расширению — 80% работает, 20% (generated, polyglot, шаблоны) — нет.
- Монорепы — ад: `frontend/`, `backend/`, `shared/`.
- Отладка: непонятно, правило не сработало или отфильтровалось.
- **Ложный negative хуже, чем ложный positive.** Пропущенная уязвимость — провал продукта.

### 6.2. Что делать вместо

**Детерминированная фильтрация по расширениям.** Язык по расширению файла. Если файлов языка < 5 — правила этого языка не загружаются. Просто, надёжно, предсказуемо.

**Явные профили в конфиге (для сложных случаев):**

```yaml
scanners:
  semgrep:
    profiles:
      - name: "backend"
        path: "backend/"
        languages: ["python", "go"]
      - name: "frontend"
        path: "frontend/"
        languages: ["javascript"]
```

Это **декларация**, не автоопределение. Пользователь контролирует.

**Если профили не заданы — используем все правила.** Да, медленнее. Да, больше FP. Но **безопасно**.

### 6.3. Компромисс на будущее

Если через полгода окажется, что полный набор правил слишком медленный — добавить автоопределение как **opt-in** (`auto_profile: true`), только в дополнение к явным профилям, с логированием отфильтрованного. **Не в v1.**

---

## 7. Лицензионная изоляция AGPL

**TruffleHog (AGPL-3.0):**
- `Dockerfile` — официальный релиз, исходники не вендорим.
- `TruffleHogAdapter` — только `subprocess.run`, без импорта и линковки.
- Без патчей. Кастомные детекторы — через `--config` (данные, не производная работа).
- В `docs/architecture.md`: «TruffleHog — внешний инструмент под AGPL-3.0; AppSecGate не производная работа».

**Semgrep (движок, LGPL-2.1)** — внешний бинарник.
**Gitleaks (MIT)** — без ограничений.

---

## 8. Что менять в коде (карта v1)

| Файл | Изменение |
|---|---|
| `rules/` | bundle + `manifest.yaml` + `THIRD_PARTY_NOTICES.md` + `opengrep-community/` (без `jetbrains/`) |
| `rules/license_guard.py` | проверка лицензий vs `distribution_mode` |
| `config/loader.py` | + `RuleResolver` и `LicenseGuard` |
| `config/models.py` | `rules_path`, `overrides`, `distribution_mode`, `network.mode` |
| `scanners/semgrep.py` | локальные директории правил |
| `scanners/gitleaks.py` | `--config` в команду |
| `scanners/trufflehog.py` | `--config`; без вендоринга |
| `scanners/registry.py` | прокидывать resolved-путь |
| `Dockerfile` | `COPY rules/` + seed Trivy DB + build-args |
| `storage/db.py` | `ruleset_hash` включает `distribution_mode` |
| `docs/architecture.md` | раздел «Лицензионная модель» |
| `THIRD_PARTY_NOTICES.md` | сводка лицензий |

---

## 9. Сценарии поставки

**MIT-версия (v1):**
```yaml
distribution_mode: "mit"
bundles: [community-sast, base, secrets, trufflehog-custom]
```
Публикуется свободно.

**Коммерческая версия (будущее):** тот же код, другой `manifest.yaml`. `LicenseGuard` блокирует случайное попадание `restricted`-правил.

---

## 10. Чеклист v1

1. ✅ Вендорить `opengrep-sast-rules` (без `jetbrains/`).
2. ✅ `manifest.yaml` с лицензиями и `distribution_mode: mit`.
3. ✅ `RuleResolver` + `LicenseGuard` (~200 строк каждый).
4. ✅ Overlay-слои (default/project/user) без deep-merge.
5. ✅ Trivy DB seed + проверка возраста + warning.
6. ✅ `network.mode: offline` по умолчанию.
7. ✅ Никакого автоопределения языков.
8. ✅ CI-пайплайн валидации bundle.

**Это ~80% ценности при ~20% сложности.**

---

## 11. Открытые вопросы к спайку

1. Точный список правил в `opengrep-sast-rules`, исключаемых из-за Commons Clause.
2. Совместимость схемы custom-detectors TruffleHog 3.82.
3. Реальный размер `trivy-db-seed` на amd64.
4. Нужно ли снимать `--network=none` для sync или выносить в отдельную команду.
5. Формат `THIRD_PARTY_NOTICES.md` для автогенерации (Syft/Grype в CI).
6. Юридическая проверка изоляции `subprocess` для AGPL в юрисдикции распространения.