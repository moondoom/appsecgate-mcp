SERVER_DIR     := mcp-server
IMAGE          ?= moondoom/appsecgate-mcp
VERSION        ?= 0.1.0
TAG            ?= $(IMAGE):$(VERSION)
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
        docker-build docker-run docker-down docker-push \
        clean

help: ## Показать список основных команд
	@echo "Основные цели:"
	@echo "  setup        Установить зависимости через uv (включая dev)"
	@echo "  test         Запустить тесты"
	@echo "  test-file    Запустить один файл (make test-file FILE=tests/test_server_smoke.py)"
	@echo "  lint         Проверить код ruff'ом"
	@echo "  format       Отформатировать код ruff'ом"
	@echo "  check        Полная проверка перед коммитом (lint + test)"
	@echo "  docker-build Собрать Docker-образ"
	@echo "  docker-run   Запустить MCP-сервер в Docker"
	@echo "  docker-down  Остановить контейнеры"
	@echo "  docker-push  Залогиниться и запушить образ"
	@echo "  clean        Удалить локальные артефакты uv"

setup: ## Установить зависимости через uv (включая dev)
	cd $(SERVER_DIR) && uv sync --extra dev

test: ## Запустить тесты
	cd $(SERVER_DIR) && uv run pytest

lint: ## Проверить код ruff'ом
	cd $(SERVER_DIR) && uv run ruff check src tests

format: ## Отформатировать код ruff'ом
	cd $(SERVER_DIR) && uv run ruff check --fix src tests
	cd $(SERVER_DIR) && uv run ruff format src tests

test-file: ## Запустить один тестовый файл (FILE=tests/test_server_smoke.py)
	@test -n "$(FILE)" || (echo "Укажите FILE=путь/к/тесту.py" && exit 1)
	cd $(SERVER_DIR) && uv run pytest $(FILE)

check: lint test ## Полная проверка перед коммитом

docker-build: ## Собрать Docker-образ (context = mcp-server)
	docker buildx build $(BUILDX_CACHE_ARGS) \
	  --build-arg WITH_JAVA_DB=$(WITH_JAVA_DB) \
	  -t $(TAG) \
	  -f $(SERVER_DIR)/Dockerfile \
	  --load \
	  $(SERVER_DIR)

docker-run: ## Запустить MCP-сервер в Docker (PROJECT_PATH по умолчанию — текущий каталог)
	PROJECT_PATH=$(PROJECT_PATH) docker compose -f $(SERVER_DIR)/docker-compose.yml run --rm appsecgate-mcp

docker-down: ## Остановить контейнеры (volumes по умолчанию сохраняются)
	docker compose -f $(SERVER_DIR)/docker-compose.yml down

docker-push: ## Залогиниться в Docker Hub и запушить образ
	docker login
	docker push $(TAG)

clean: ## Удалить локальные артефакты uv
	cd $(SERVER_DIR) && rm -rf .venv .pytest_cache .ruff_cache