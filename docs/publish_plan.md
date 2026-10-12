# План публикации AppSecGate MCP в Docker Hub

> Версия: 1.1
> Дата: 2026-10-09
> Область: публикация pet-проекта, ручной push + автоматизация через GitHub Actions

---

## 1. Подготовка: что решить до первого `push`

### 1.1. Пространство имён (namespace)

В `session-handoff.md` образ собирается как `appsecgate/mcp:0.1.0`.
Здесь `appsecgate` — namespace. На Docker Hub namespace может быть:

- твоим **username**;
- названием **организации**, где ты owner/editor.

Для pet-проекта проще всего использовать свой username:

```bash
<username>/appsecgate-mcp:0.1.0
```

Требования к имени репозитория:

- только строчные буквы, цифры, дефисы и подчёркивания;
- длина от 2 до 255 символов;
- уникально внутри твоего namespace.

> Важно: переименовать уже созданный репозиторий на Docker Hub нельзя.
> Если позже захочешь вынести в организацию — это делается через создание нового репозитория.

### 1.2. Аутентификация: Personal Access Token

Не используй пароль от аккаунта. Создай **Personal Access Token (PAT)**:

1. Docker Hub → **Account Settings → Security → New Access Token**.
2. Права: **Read & Write**.
3. Сохрани токен — он показывается только один раз.

Логин:

```bash
echo $DOCKER_HUB_TOKEN | docker login -u $DOCKER_HUB_USERNAME --password-stdin
```

---

## 2. Процесс публикации вручную

### 2.1. Сборка

```bash
# Из корня репозитория. Тег сразу под свой namespace
make docker-build TAG=<username>/appsecgate-mcp:0.1.0
```

### 2.2. Перетегирование под свой namespace

Отдельный шаг не нужен: `TAG` задаётся сразу при сборке (см. 2.1).
Если образ уже собран под другим именем, используй `docker tag`: он не копирует образ, а создаёт новый указатель на те же слои.

### 2.3. Push

```bash
docker push <username>/appsecgate-mcp:0.1.0
```

Проверка: Docker Hub → репозиторий → вкладка **Tags**.

---

## 3. Стратегия тегирования

Docker Hub позволяет хранить несколько тегов для одного репозитория.

Рекомендуемый минимум:

| Тег | Назначение |
|-----|------------|
| `0.1.0` | Иммутабельный тег конкретного релиза. Для воспроизводимости. |
| `latest` | Подвижный тег, указывает на последний стабильный релиз. |

Дополнительно можно добавить `0.1` (минорная версия), но для 0.x это не обязательно.

> Главное — не перезаписывай версионные теги после публикации.
> В настройках репозитория можно включить **Immutable Tags**.

---

## 4. README и описание на Docker Hub

Для ручного push Docker Hub **не читает README** из образа или Git-репозитория.
Описание нужно заполнить вручную в разделе **Information** на сайте Docker Hub.

Как минимум заполни **short description** — оно отображается в поиске:

> AppSecGate MCP — локальный сканер безопасности для AI-агентов (Semgrep, Gitleaks, Trivy).
> Работает офлайн, non-root, read-only rootfs.

Для автоматической синхронизации README можно использовать GitHub Action:

- `peter-evans/dockerhub-description`

---

## 5. GitHub: настройка репозитория

### 5.1. Создание репозитория

1. Создай **приватный** репозиторий на GitHub (например, `appsecgate-mcp`).
2. Залей код.
3. Добавь `LICENSE`, `README.md`, `.gitignore`.
4. Убедись, что CI зелёный (см. раздел 6).
5. Переведи репозиторий в **public**.

Приватный старт нужен, чтобы случайно не закоммитить секреты:
`.appsecgate-mcp/config.yaml`, `shown_findings.db`, `*.sqlite`, `.env`.

### 5.2. Secrets и Variables

В GitHub-репозитории: **Settings → Secrets and variables → Actions**.

**Repository secrets:**

| Имя | Значение |
|-----|----------|
| `DOCKERHUB_USERNAME` | Твой Docker ID |
| `DOCKERHUB_TOKEN` | PAT с правами Read & Write |

**Repository variables** (опционально):

| Имя | Значение |
|-----|----------|
| `DOCKER_USERNAME` | Твой Docker ID (если хочешь использовать `vars`) |

Docker официально рекомендует хранить PAT как **secret** `DOCKERHUB_TOKEN`, а username — либо как secret, либо как variable[reference:0]. Не используй пароль аккаунта — только PAT[reference:1].

### 5.3. GitHub Container Registry (ghcr.io) — альтернатива

Если не хочешь зависеть от Docker Hub, можно пушить в **GitHub Container Registry**:

```bash
ghcr.io/<owner>/<repo>:tag
```

Аутентификация — через встроенный `GITHUB_TOKEN`, **без дополнительных секретов**[reference:2]:

```yaml
- uses: docker/login-action@v3
  with:
    registry: ghcr.io
    username: ${{ github.actor }}
    password: ${{ secrets.GITHUB_TOKEN }}
```

Плюсы: нет отдельного PAT, нет rate limits Docker Hub для анонимных pull.
Минус: образы видны только внутри GitHub-экосистемы (для pet-проекта это редко проблема).

Можно пушить **в оба registry** — GitHub Actions это позволяет без проблем.

---

## 6. Базовые рантаймы для CI

### 6.1. Раннер: `ubuntu-latest`

GitHub-hosted раннер `ubuntu-latest` сейчас базируется на **Ubuntu 24.04 LTS**[reference:3].

> **Важно на будущее**: GitHub начал миграцию `ubuntu-latest` на **Ubuntu 26.04**.
> Раскатка запланирована на период **с 19 октября по 19 ноября 2026 года**[reference:4].
> Для pet-проекта это не критично, но если CI внезапно сломается в этот период — причина может быть в миграции.

На раннере уже предустановлены: Docker, Git, build-essential, популярные language runtimes и CI-утилиты. Для Python-проекта с Docker обычно **ничего дополнительно устанавливать не нужно**, кроме `uv` и самого Python.

### 6.2. Python: версия и установка

В проекте зафиксирован **Python 3.12** (см. `pyproject.toml` / `.python-version`).

Два способа задать версию в CI:

**Способ 1: через `setup-uv` (рекомендуемый для uv-проектов)**

```yaml
- uses: astral-sh/setup-uv@v5
  with:
    enable-cache: true
- run: uv python install 3.12
```

`setup-uv` сам скачает нужную версию и закэширует её[reference:5].

**Способ 2: через `actions/setup-python@v5`**

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: "3.12"
```

Этот способ может быть **быстрее**, потому что GitHub кэширует Python-версии вместе с раннером[reference:6].

Для pet-проекта **любой из них рабочий**. Если ты уже используешь `uv` в разработке — бери `setup-uv` с `enable-cache: true`.

### 6.3. Кэширование uv

`astral-sh/setup-uv` имеет встроенную поддержку кэша[reference:7]:

```yaml
- uses: astral-sh/setup-uv@v5
  with:
    enable-cache: true
```

Это сохраняет скачанные пакеты между запусками CI и заметно ускоряет сборку.

Если нужен ручной контроль — можно использовать `actions/cache` с ключом по `uv.lock`. Для CI-оптимизации есть команда `uv cache prune --ci`[reference:8].

### 6.4. Docker в CI

На `ubuntu-latest` Docker **уже предустановлен**. Для сборки образа нужен только `docker/build-push-action` и (опционально) `docker/setup-buildx-action` для multi-platform сборки.

Для `linux/amd64` (целевая платформа проекта) Buildx не обязателен, но его установка не помешает:

```yaml
- uses: docker/setup-buildx-action@v3
```

### 6.5. Сводная таблица рантаймов

| Компонент | Версия / значение | Как задаётся |
|-----------|-------------------|--------------|
| Раннер | `ubuntu-latest` (24.04 → 26.04 в ноябре 2026) | `runs-on: ubuntu-latest` |
| Python | 3.12 | `uv python install 3.12` или `setup-python@v5` |
| Пакетный менеджер | `uv` (последняя стабильная) | `astral-sh/setup-uv@v5` |
| Docker | предустановлен на раннере | не требует установки |
| Docker Buildx | опционально | `docker/setup-buildx-action@v3` |
| Git | предустановлен | не требует установки |

---

## 7. GitHub Actions: рабочие примеры

### 7.1. CI: тесты и линт

Запускается на каждый push и pull request. Проверяет, что код не сломан, до публикации образа.

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Set up Python
        run: uv python install 3.12

      - name: Install dependencies
        run: uv sync --extra dev

      - name: Lint with ruff
        run: uv run ruff check src tests

      - name: Run tests
        run: uv run pytest -q
```

Этот workflow **не публикует** ничего — он только проверяет качество. Зелёный бейдж CI в README сразу повышает доверие к проекту.

### 7.2. Публикация Docker-образа в Docker Hub

Запускается только при создании Git-тега вида `v0.1.0`.

```yaml
name: Publish Docker image

on:
  push:
    tags: ['v*.*.*']

jobs:
  push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Login to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: ./mcp-server
          push: true
          tags: |
            ${{ secrets.DOCKERHUB_USERNAME }}/appsecgate-mcp:${{ github.ref_name }}
            ${{ secrets.DOCKERHUB_USERNAME }}/appsecgate-mcp:latest
```

**Как это работает**:

- Триггер `on: push: tags: ['v*.*.*']` срабатывает только на теги вида `v0.1.0`, `v1.2.3` и т.д.[reference:9].
- `github.ref_name` подставляет имя тега **без** префикса `refs/tags/`, то есть `v0.1.0`.
- Если не хочешь префикс `v` в теге Docker-образа — используй `${{ github.ref_name }}` и назови Git-тег `0.1.0` без `v`.

### 7.3. Публикация в GHCR (альтернатива или дополнение)

```yaml
- name: Login to GHCR
  uses: docker/login-action@v3
  with:
    registry: ghcr.io
    username: ${{ github.actor }}
    password: ${{ secrets.GITHUB_TOKEN }}

- name: Build and push to GHCR
  uses: docker/build-push-action@v5
  with:
    context: ./mcp-server
    push: true
    tags: |
      ghcr.io/${{ github.repository }}:${{ github.ref_name }}
      ghcr.io/${{ github.repository }}:latest
```

`GITHUB_TOKEN` — встроенный, дополнительных секретов не требует[reference:10].

### 7.4. Порядок публикации

1. Убедись, что CI зелёный на `main`.
2. Создай Git-тег: `git tag v0.1.0 && git push origin v0.1.0`.
3. Workflow `Publish Docker image` запустится автоматически.
4. Проверь Docker Hub → Tags.

> Ручной `docker push` с локальной машины можно использовать как fallback,
> но автоматизация через GitHub Actions даёт воспроизводимую сборку в чистом окружении.

---

## 8. Дополнительные нюансы

### 8.1. Размер образа

В образе четыре сканера: gitleaks, trufflehog, trivy, semgrep.
Целевой размер в архитектуре — **< 500 МБ** (multi-stage build).

Проверка:

```bash
docker images
```

Если размер сильно больше — подумать об оптимизации.
Для pet-проекта это не блокер.

### 8.2. Rate limits Docker Hub

- Анонимные pull: **100 запросов за 6 часов** с одного IP.
- Аутентифицированные бесплатные аккаунты: **200 запросов за 6 часов**.

Для pet-проекта это не проблема, но стоит держать в уме.

### 8.3. Приватность образа

Для pet-проекта логично сделать репозиторий **публичным**.
Бесплатный аккаунт Docker Hub позволяет:

- 1 приватный репозиторий;
- неограниченное число публичных.

Публичный образ проще для распространения.

### 8.4. Immutable Tags

В настройках репозитория Docker Hub можно включить **Immutable Tags**.
Тогда версионные теги (`0.1.0`) нельзя будет перезаписать — только добавить новые.

Для pet-проекта это полезная защита от случайной перезаписи.

---

## 9. Итоговый чеклист

### Docker Hub

- [ ] Создать PAT в Docker Hub (Read & Write).
- [ ] Создать репозиторий на Docker Hub под своим username или организацией.
- [ ] Перетегировать локальный образ под `<username>/appsecgate-mcp:0.1.0`.
- [ ] Залогиниться через `docker login` с PAT.
- [ ] Запушить образ.
- [ ] Заполнить описание репозитория вручную (или настроить синхронизацию через GitHub Action).
- [ ] Добавить `latest` тег.
- [ ] (Опционально) Включить Immutable Tags.

### GitHub

- [ ] Создать приватный репозиторий, залить код.
- [ ] Добавить `LICENSE`, `README.md`, `.gitignore`.
- [ ] Добавить secrets `DOCKERHUB_USERNAME` и `DOCKERHUB_TOKEN`.
- [ ] (Опционально) Добавить variable `DOCKER_USERNAME`.
- [ ] Создать `.github/workflows/ci.yml` (тесты + линт).
- [ ] Создать `.github/workflows/docker-publish.yml` (публикация при теге `v*.*.*`).
- [ ] Убедиться, что CI зелёный.
- [ ] Перевести репозиторий в public.
- [ ] Создать Git-тег `v0.1.0` и запушить — проверить, что workflow отработал.
- [ ] (Опционально) Настроить публикацию в GHCR параллельно с Docker Hub.

---

## 10. Полезные команды

```bash
# Логин через PAT
echo $DOCKER_HUB_TOKEN | docker login -u $DOCKER_HUB_USERNAME --password-stdin

# Сборка из корня репозитория (тег под свой namespace)
make docker-build TAG=<username>/appsecgate-mcp:0.1.0

# Дополнительный тег latest
docker tag <username>/appsecgate-mcp:0.1.0 <username>/appsecgate-mcp:latest

# Push
docker push <username>/appsecgate-mcp:0.1.0
docker push <username>/appsecgate-mcp:latest

# Git tag
git tag v0.1.0
git push origin v0.1.0

# Проверка
docker images
```

---

> Если позже понадобится синхронизация README с Docker Hub,
> multi-platform сборка (amd64 + arm64) или публикация в GHCR —
> это добавляется отдельными шагами в существующие workflow.