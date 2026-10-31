SERVER_DIR     := mcp-server
MASTER_DIR     := appsecgate-master
IMAGE          ?= moondoom/appsecgate-mcp
VERSION        ?= 0.1.0
TAG            ?= $(IMAGE):$(VERSION)
MASTER_IMAGE   ?= moondoom/appsecgate-master
MASTER_VERSION ?= 0.1.0
MASTER_TAG     ?= $(MASTER_IMAGE):$(MASTER_VERSION)
PROJECT_PATH   ?= $(CURDIR)
WITH_JAVA_DB   ?= false

# Кэш BuildKit (type=local). По умолчанию пусто — кэш не экспортируется.
# Для экспорта нужен builder на драйвере docker-container:
#   docker buildx create --name appsecgate --driver docker-container --use
# Затем: make docker-build BUILDX_CACHE_DIR=$(CURDIR)/.buildx-cache
BUILDX_CACHE_DIR ?=
ifeq ($(strip $(BUILDX_CACHE_DIR)),)
BUILDX_CACHE_ARGS :=
else
BUILDX_CACHE_ARGS := --cache-from=type=local,src=$(BUILDX_CACHE_DIR) --cache-to=type=local,dest=$(BUILDX_CACHE_DIR),mode=max
endif

.PHONY: help setup test test-file lint format check \
        master-setup master-lint master-test master-check master-format \
        docker-build docker-run docker-down docker-push docker-master-build \
        compose-up compose-down compose-edge-sync \
        clean

help: ## Показать список основных команд
	@echo "Основные цели:"
	@echo "  setup          Установить зависимости обоих пакетов (uv, incl. dev)"
	@echo "  test           Запустить тесты mcp-server"
	@echo "  test-file      Запустить один файл (make test-file FILE=tests/test_server_smoke.py)"
	@echo "  lint           Проверить код mcp-server ruff'ом"
	@echo "  format         Отформатировать mcp-server ruff'ом"
	@echo "  master-setup   Установить зависимости appsecgate-master (uv)"
	@echo "  master-test    Запустить тесты appsecgate-master"
	@echo "  master-lint    Проверить код appsecgate-master ruff'ом"
	@echo "  master-format  Отформатировать appsecgate-master ruff'ом"
	@echo "  check          Полная проверка обоих пакетов (lint + test)"
	@echo "  docker-build   Собрать Docker-образ mcp-server"
	@echo "  docker-master-build  Собрать Docker-образ master"
	@echo "  compose-up     Поднять master-сервер (корневой compose)"
	@echo "  compose-edge-sync  Запустить edge-синхронизацию"
	@echo "  compose-down   Остановить контейнеры корневого compose"
	@echo "  docker-run     Запустить MCP-сервер в Docker"
	@echo "  docker-down    Остановить контейнеры"
	@echo "  docker-push    Залогиниться и запушить образ"
	@echo "  clean          Удалить локальные артефакты uv обоих пакетов"

setup: ## Установить зависимости через uv (включая dev)
	cd $(SERVER_DIR) && uv sync --extra dev
	cd $(MASTER_DIR) && uv sync --extra dev

master-setup: ## Установить зависимости appsecgate-master через uv
	cd $(MASTER_DIR) && uv sync --extra dev

test: ## Запустить тесты mcp-server
	cd $(SERVER_DIR) && uv run pytest

lint: ## Проверить код mcp-server ruff'ом
	cd $(SERVER_DIR) && uv run ruff check src tests

format: ## Отформатировать код mcp-server ruff'ом
	cd $(SERVER_DIR) && uv run ruff check --fix src tests
	cd $(SERVER_DIR) && uv run ruff format src tests

master-test: ## Запустить тесты appsecgate-master
	cd $(MASTER_DIR) && uv run pytest

master-lint: ## Проверить код appsecgate-master ruff'ом
	cd $(MASTER_DIR) && uv run ruff check src tests

master-format: ## Отформатировать код appsecgate-master ruff'ом
	cd $(MASTER_DIR) && uv run ruff check --fix src tests
	cd $(MASTER_DIR) && uv run ruff format src tests

test-file: ## Запустить один тестовый файл (FILE=tests/test_server_smoke.py)
	@test -n "$(FILE)" || (echo "Укажите FILE=путь/к/тесту.py" && exit 1)
	cd $(SERVER_DIR) && uv run pytest $(FILE)

check: lint test master-lint master-test ## Полная проверка обоих пакетов перед коммитом

docker-build: ## Собрать Docker-образ (context = mcp-server)
	docker buildx build $(BUILDX_CACHE_ARGS) \
	  --build-arg WITH_JAVA_DB=$(WITH_JAVA_DB) \
	  -t $(TAG) \
	  -f $(SERVER_DIR)/Dockerfile \
	  --load \
	  $(SERVER_DIR)

docker-master-build: ## Собрать Docker-образ master (context = appsecgate-master)
	docker buildx build $(BUILDX_CACHE_ARGS) \
	  -t $(MASTER_TAG) \
	  -f $(MASTER_DIR)/Dockerfile \
	  --load \
	  $(MASTER_DIR)

compose-up: ## Поднять master-сервер (корневой compose, master + edge)
	docker compose up -d master

compose-edge-sync: ## Запустить edge-синхронизацию (корневой compose)
	docker compose run --rm edge

compose-down: ## Остановить контейнеры корневого compose
	docker compose down

docker-run: ## Запустить MCP-сервер в Docker (PROJECT_PATH по умолчанию — текущий каталог)
	PROJECT_PATH=$(PROJECT_PATH) docker compose -f $(SERVER_DIR)/docker-compose.yml run --rm appsecgate-mcp

docker-down: ## Остановить контейнеры (volumes по умолчанию сохраняются)
	docker compose -f $(SERVER_DIR)/docker-compose.yml down

docker-push: ## Залогиниться в Docker Hub и запушить образ
	docker login
	docker push $(TAG)

clean: ## Удалить локальные артефакты uv обоих пакетов
	cd $(SERVER_DIR) && rm -rf .venv .pytest_cache .ruff_cache
	cd $(MASTER_DIR) && rm -rf .venv .pytest_cache .ruff_cache