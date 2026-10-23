# AppSecGate MCP

> **Английская версия — основная:** [README.md](README.md)
> Ниже — русскоязычная версия для разработчиков, работающих с AI-агентами.

**Локальный security-сканер для AI-агентов и разработчиков.**

AppSecGate -- MCP-сервер, который сканирует файлы, diffы и целые проекты
прямо внутри Claude Code, Cursor, Cline и Continue. Офлайн, без отправки кода
куда-либо, без LLM-вызовов на сервере.

## Проблема

AI-агенты пишут код быстрее, чем security успевает его проверить. AppSecGate
закрывает этот разрыв:

- Сканирует изменения сразу после того, как агент написал код -- до коммита.
- Ведет журнал показанных находок (shown_findings.db) -- каждая находка
  регистрируется до того, как её увидят.
- Идентифицирует находки детерминированным fingerprint -- повторный скан
  не плодит дубликатов.
- Готовит контекстные данные для LLM-агента (ContextPack) -- не промпт, а
  данные: фрагмент кода, документация правила, дедуплицированные находки.

## Ключевые концепции

- **Три контура сканирования:** warn-only локально, блокировка в CI (Фаза 2),
  аудит после релиза.
- **Пять ролей (Фаза 3):** Developer, Lead, AppSec, CISO, Admin.
- **Жизненный цикл находки:** detected shown suppressed/false_positive
  accepted/fixed verified/resurrected/blamed.

## MCP-тулы (14)

| Инструмент | Что делает |
|------------|------------|
| scan_file | Сканирует один файл. |
| scan_diff | Сканирует staged + unstaged + untracked изменения в git. |
| scan_project | Сканирует проект или директорию. |
| get_fix_context | Контекстный пакет для фикса (находка + код + правило). |
| get_fix_context_batch | Пакеты для нескольких находок (до 20). |
| verify_fix | Проверяет фикс: пересканирует файл, сравнивает fingerprint. |
| verify_fix_batch | Проверяет до 20 находок. |
| query_findings_db | Только SELECT по публичным представлениям. |
| export_snapshot | Экспорт находок в ndjson (parquet -- Фаза 2). |
| get_config / update_config | Чтение и обновление конфигурации сессии. |
| submit_feedback | Обратная связь: FALSE_POSITIVE / CONFIRMED / WONT_FIX. |
| get_scan_history | Журнал показанных находок с попытками верификации. |
| suppress_finding | Локальное подавление находки. |

## Сканеры (Фаза 1)

- **SAST:** Semgrep (локальный Rules Bundle, без обращений к реестру).
- **Секреты:** Gitleaks, TruffleHog (редакция до записи в БД).
- **SCA:** Trivy (база уязвимостей на момент сборки образа).

## Модель безопасности

- **Read-only монтирование.** Сервер никогда не пишет в файлы проекта.
- **Offline по умолчанию.** network_mode: none -- никаких HTTP-вызовов.
- **Ноль LLM-вызовов.** На сервере нет вызовов к языковым моделям.
- **Редакция секретов.** При записи, а не при отдаче.
- **Контейнер:** non-root, read-only rootfs, cap-drop=ALL.

## Быстрый старт

```bash
# Сборка образа
make docker-build

# Запуск в docker-compose
PROJECT_PATH=/путь/к/проекту docker compose run --rm appsecgate-mcp

# Или напрямую
docker run --rm -i --network=none --read-only \
  --tmpfs=/tmp:size=100M,mode=1777 --cap-drop=ALL \
  --security-opt=no-new-privileges:true \
  -v .:/workspace:ro \
  -v appsecgate-cache:/home/appsecgate/.cache \
  -v appsecgate-data:/home/appsecgate/.appsecgate-mcp \
  moondoom/appsecgate-mcp:0.1.0 \
  --transport stdio --project /workspace
```

## Разработка

```bash
make setup          # создание uv-окружения
make check          # ruff + pytest (283 теста)
make docker-build   # moondoom/appsecgate-mcp:0.1.0
```

## Структура репозитория

```
appsecgate-mcp/
  README.md                  # Основная (английская) версия
  README.ru.md               # Этот файл
  llms.txt                   # Индекс для AI-агентов
  server.json                # MCP Registry
  docs/
    publishing.md            # План публикации
    deploy-agents.md         # Развертывание для AI-агентов
    architecture.md          # Архитектура
    fix-workflow-design.md   # Спецификация Фазы 1
    open-tasks.md            # Открытые задачи
    e2e-test-plan.md         # План E2E
    reports/                 # Отчеты (E2E, замеры)
    adr/                     # Architectural Decision Records
    product-vision.md        # Видение продукта
  mcp-server/                # Код сервера
    src/appsecgate_mcp/      # MCP-тулы, сканеры, storage
    config/default.yaml      # Конфигурация по умолчанию
    tests/                   # 283 теста
  Makefile
  docker-compose.yml
```

## Документация

- [Развертывание для AI-агентов](docs/deploy-agents.md) -- все четыре клиента
- [Архитектура](docs/architecture.md)
- [Спецификация Фазы 1](docs/fix-workflow-design.md)
- [Видение продукта](docs/product-vision.md)
- [План публикации](docs/publishing.md)

## Лицензия

MIT -- см. [LICENSE](LICENSE).