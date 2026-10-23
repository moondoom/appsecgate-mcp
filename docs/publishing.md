# План публикации и дистрибуции AppSecGate MCP

> **Версия:** 2.0
> **Дата:** 2026-10-23
> **Область:** упаковка проекта, публикация в Docker Hub и официальном MCP Registry, размещение в каталогах, продвижение, английское зеркало

---

## 0. Стратегическая последовательность (главное)

Порядок действий критичен. **Сначала — упаковка репозитория** (без неё реестры и HN дадут только временный всплеск). **Затем — официальный MCP Registry** (это источник истины, из которого синхронизируются остальные каталоги). **Потом — Docker Hub и awesome-списки.** **И только после этого — активное продвижение** (Show HN, Reddit, Dev.to).

Официальный MCP Registry — это канонический источник, из которого **PulseMCP, Smithery и другие агрегаторы** автоматически забирают данные. Один раз публикуете `server.json` в реестре — и появляетесь в экосистеме. Поэтому реестр идёт **до** Docker Hub и до PR в awesome-списки.

---

## 1. Упаковка проекта (до любых размещений)

### 1.1. Английский README как основной

Репозиторий сейчас на русском — это автоматически отсекает 90% каналов дистрибуции MCP. Английский README должен быть **не переводом**, а переупаковкой под боль. Позиционирование: *«AI agents ship code faster than security can review it. AppSecGate scans the diff right inside Cline/Cursor and syncs findings with ASOC — without sending your code anywhere.»*

**Обязательные элементы:**
- **Quick Install** для Claude Code, Cursor, Cline, Continue — готовые JSON-блоки, а не «см. docs».
- **Таблица 14 инструментов** с одной строкой на каждый — агенты это цитируют.
- **GIF-демо** установки и прогона на Juice Shop.
- **Раздел «When to use / When NOT to use»** — честность повышает цитируемость.
- **Лицензия** (MIT или Apache-2.0) — без неё многие реестры и awesome-списки не примут.

Русский README — дополнительный (`README.ru.md`) со ссылкой из основного.

Дополнительно, но обязательно привести `docs/` порядок, лише удалить или перетасовать в отдельные каталоги и примести именование документов к единому формату.

### 1.2. `llms.txt` в корне репозитория

`llms.txt` — это Markdown-файл в корне сайта (или репозитория), который даёт AI-агентам структурированный индекс ключевых страниц и machine-readable ссылок. Спецификация (`llmstxt.org`) определяет его как «краткую справочную информацию, руководство и ссылки на подробные Markdown-файлы». Файл должен быть **до 2000 токенов** — агенты используют его как pre-flight проверку, а не как замену документации.

Минимальный `llms.txt` для AppSecGate: краткое описание, ссылки на Quick Install, список инструментов с одной строкой на каждый, ссылка на `docs/deploy-agents.md`.

### 1.3. Социальное превью GitHub (1280×640)

GitHub требует **ровно 1280×640 px** для OpenGraph-карточки, которая отображается при шаринге ссылки в Slack, Twitter/X, LinkedIn, Discord. Изображение должно оставаться читаемым в миниатюре ~640×320. Загружается в **Settings → General → Social preview**. Это бесплатный канал, который сейчас теряется.

### 1.4. GitHub Pages как лендинг

Если страница `moondoom.github.io/appsecgate-mcp/` существует, она должна быть доступна, содержать те же Quick Install и `llms.txt`. GitHub Pages отлично подходит для статических лендингов с `llms.txt`: файл кладётся в корень сайта, и агенты могут его прочитать. Если страницы нет — это не блокер, но реестры часто требуют «website» в листинге.

### 1.5. Docker Hub: синхронизация описания (не только ручной push)

Docker Hub **больше не синхронизирует README из GitHub автоматически**. Для pet-проекта можно заполнить описание вручную, но лучше добавить в `docker-publish.yml` шаг `peter-evans/dockerhub-description@v4`, который обновляет overview из `README.md` при каждом релизе. Это устраняет дрейф между репозиторием и Docker Hub.

---

## 2. Публикация в официальном MCP Registry

### 2.1. Аутентификация и имя

Реестр поддерживает два способа аутентификации, и **выбор способа определяет имя сервера** в `server.json`:

| Способ | Формат имени | Пример |
|---|---|---|
| **GitHub-based** (рекомендуется для pet-проекта) | `io.github.username/*` | `io.github.moondoom/appsecgate-mcp` |
| Domain-based | `com.example.*/*` | `io.modelcontextprotocol/everything` |

Для AppSecGate: **`io.github.moondoom/appsecgate-mcp`**.

Аутентификация через `mcp-publisher login github` — OAuth-флоу, в терминале появится код для ввода на `github.com/login/device`.

### 2.2. `server.json`

`mcp-publisher` читает `server.json` и отправляет его в реестр. Ключевые поля: `$schema`, `name` (в формате `io.github.username/repo`), `title`, `description` (одно предложение, ≤100 символов), `version`, `packages`.

Важно: реестр требует **публичный GitHub-репозиторий** и (для валидации) работающий MCP-эндпоинт или пакет. Для локального stdio-сервера реестр проверяет, что `server.json` указывает на публичный пакет и что `package.json#mcpName` совпадает с именем в реестре.

### 2.3. Публикация

```bash
mcp-publisher init          # создаёт server.json
# отредактировать server.json
mcp-publisher validate      # проверка схемы
mcp-publisher login github
mcp-publisher publish
```

---

## 3. Размещение в каталогах (после реестра)

### 3.1. Glama (обязательно до awesome-mcp-servers)

Glama — крупнейший каталог с автоматической индексацией open-source серверов. **Критично:** `punkpeye/awesome-mcp-servers` теперь **требует** листинга на Glama и **Glama score badge** в PR. Без этого PR закроют.

Процесс: submit на `glama.ai/mcp/servers`, дождаться прохождения проверок (сервер должен стартовать и отвечать на introspection requests), затем взять badge по шаблону `https://glama.ai/mcp/servers/OWNER/REPO/badges/score.svg`.

### 3.2. `punkpeye/awesome-mcp-servers` (30K+ звёзд)

Формат записи: `- [owner/repo](url) 🐍 ☁️ - Description`. Категория — **Security**. Обязательные бейджи: язык (Python — 🐍), scope (local — 🏠), опционально официальные. PR — одна запись, заголовок вида `Add AppSecGate-MCP to Security`.

**Условие:** сначала Glama, потом badge в описании, потом PR.

### 3.3. Smithery

Smithery требует **публичный HTTPS URL** MCP-сервера для хостинга (stdio-серверы можно упаковать как MCPB bundle). Публикация через `smithery.ai/new` или CLI: `smithery mcp publish "https://your-server.com/mcp" -n @your-org/your-server`. Для локального AppSecGate это означает: либо дождаться remote-режима, либо использовать MCPB bundle для stdio.

### 3.4. PulseMCP

PulseMCP **не требует отдельной подачи** — он автоматически забирает данные из официального реестра в течение ~недели. Также есть форма `pulsemcp.com/submit`, где достаточно вставить GitHub URL. Главное — сначала быть в реестре.

### 3.5. mcp.so (опционально, позже)

Платная подача (~$39). На старте пропустить, вернуться, когда будет социальное доказательство.

---

## 4. Продвижение (после упаковки и листингов)

### 4.1. Show HN (Hacker News)

Заголовок: `Show HN: AppSecGate – scan AI-generated code inside Cline/Cursor, offline`. Правила: начинается с `Show HN:`, **≤80 символов**, без ALL CAPS, без «AI-powered», без кликбейта. В первом комментарии — история, цифры (200 находок / 15 ₽ / 50 минут), честные грабли (потеря 20 файндингов). **Никогда не просить upvotes** — это бан.

### 4.2. Reddit

- **r/ClaudeAI** — требует **50+ кармы** для постов в ленте, иначе megathread. Self-promo разрешён с ограничениями: проект должен быть **free-to-try**, с явным описанием, как Claude помог, и с соотношением **10:1** (десять полезных ответов на один промо-пост).
- **r/mcp** — аналогично, disclosed self-promo.
- **r/LocalLLaMA / r/selfhosted** — только production-ready, с раскрытием.

### 4.3. Dev.to (органический трафик месяцами)

Темы, которые уже работают в нише: *«How to Give AI Coding Agents Real-Time CVE Auditing Without API Rate Limits»*, *«How to secure AI generated code from prompt to pentest»*. Ваш угол: **local-first AppSec для AI-кода без отправки исходников наружу**. Статья на Dev.to даёт постоянный органический трафик и бэклинк.

### 4.4. Кураторские рассылки (к 1.0)

Latent Space, Ben's Bites, TLDR — не «питч», а «воспроизводимый результат + грабли + код». Письмо с ссылкой на HN-тред и цифрами.

---

## 5. Английское зеркало (стратегия)

**Делать обязательно**, но не как «два равноправных репозитория». Правильная стратегия:

| Элемент | Язык | Почему |
|---|---|---|
| `README.md` (основной) | Английский | Витрина для реестров, awesome-списков, HN |
| `README.ru.md` | Русский | Глубокое погружение для русскоязычных |
| `llms.txt` | Английский | Агенты, которых вы хотите цитировать, работают на английском |
| GitHub Pages | Английский (основной) | Реестры требуют «website» |
| Хабр-статья | Русский | Якорь доверия, ссылка на английский README |

**Сначала — английский README и `llms.txt`, потом — лендинг.** Репозиторий важнее сайта: реестры и awesome-списки ссылаются на GitHub, а не на Pages.

---

## 6. Docker Hub: публикация (интеграция с существующим планом)

### 6.1. Namespace и теги

Namespace — ваш Docker ID: `<username>/appsecgate-mcp:0.1.0`. Теги: `0.1.0` (иммутабельный) + `latest`. Включить **Immutable Tags** в настройках репозитория.

### 6.2. GitHub Actions

Два workflow:
- `ci.yml` — тесты и линт на каждый push/PR.
- `docker-publish.yml` — сборка и push по тегу `v*.*.*`, плюс шаг `peter-evans/dockerhub-description@v4` для синхронизации README.

Секреты: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` (PAT с Read & Write). Альтернатива — GHCR через `GITHUB_TOKEN` без дополнительных секретов.

### 6.3. Размер образа

Целевой — **< 500 МБ** (multi-stage build). Четыре сканера: gitleaks, trufflehog, trivy, semgrep. Для pet-проекта это не блокер, но стоит держать в уме.

---

## 7. Поэтапный план (0.1 → 1.0 / стадия 3)

| Этап | Что делаете | Критерий готовности |
|---|---|---|
| **0.1 (сейчас)** | Английский README + `llms.txt` + социальное превью; официальный MCP Registry (`server.json`); Glama submit; PR в `punkpeye/awesome-mcp-servers` (с Glama badge); Docker Hub (push + синхронизация описания) | Вас можно найти в официальном реестре и в awesome-списке |
| **0.5 (2–3 недели)** | PulseMCP (авто из реестра); Smithery (MCPB bundle или remote); Show HN; r/ClaudeAI (при 50+ кармы); Dev.to-статья | Один HN-пост и одна статья, с обратной связью |
| **1.0 / стадия 3** | Docker MCP Registry, Cursor Directory, Cline Marketplace; вторая волна awesome-списков; кураторские рассылки; регулярные релизы с changelog | Вас рекомендуют в ответ на «MCP for AppSec» / «local security scanner» |

**Про «стадию 3»:** к моменту RBAC маркетинг должен быть **петлёй**: каждый релиз = повод для поста, каждый пост = ссылка на реестр, каждый реестр = бэклинк. Если к 1.0 будет только RBAC и ни одного листинга — продукт технически зрелый, но невидимый.

---

## 8. Итоговый чеклист

### Упаковка
- [ ] Английский `README.md` с Quick Install для 4 клиентов
- [ ] GIF-демо (установка + прогон на Juice Shop)
- [ ] Социальное превью 1280×640 (`Settings → Social preview`)
- [ ] `llms.txt` в корне репозитория (≤2000 токенов)
- [ ] `README.ru.md` как дополнительный

### Официальный MCP Registry
- [ ] `server.json` с именем `io.github.moondoom/appsecgate-mcp`
- [ ] `mcp-publisher login github`
- [ ] `mcp-publisher validate` → `mcp-publisher publish`

### Каталоги
- [ ] Glama submit + получение score badge
- [ ] PR в `punkpeye/awesome-mcp-servers` (категория Security, с Glama badge)
- [ ] PulseMCP (авто из реестра, проверить через ~неделю)
- [ ] Smithery (MCPB bundle или дождаться remote)
- [ ] mcp.so (опционально, позже)

### Docker Hub
- [ ] PAT (Read & Write)
- [ ] Репозиторий `<username>/appsecgate-mcp`
- [ ] CI зелёный → тег `v0.1.0` → workflow
- [ ] Синхронизация описания через `peter-evans/dockerhub-description@v4`
- [ ] Immutable Tags

### Продвижение
- [ ] Show HN (≤80 символов, без кликбейта)
- [ ] r/ClaudeAI (50+ кармы, disclosed, free-to-try, 10:1)
- [ ] Dev.to статья («local-first AppSec для AI-кода»)
- [ ] Письмо в Latent Space / Ben's Bites (к 1.0)

---

## 9. Полезные команды (дополнение)

```bash
# MCP Registry
mcp-publisher init
mcp-publisher validate
mcp-publisher login github
mcp-publisher publish

# Smithery (если есть remote URL)
smithery mcp publish "https://your-server.com/mcp" -n @your-org/appsecgate-mcp

# Docker Hub (ручной fallback)
echo $DOCKER_HUB_TOKEN | docker login -u $DOCKER_HUB_USERNAME --password-stdin
docker tag <username>/appsecgate-mcp:0.1.0 <username>/appsecgate-mcp:latest
docker push <username>/appsecgate-mcp:0.1.0
docker push <username>/appsecgate-mcp:latest
```