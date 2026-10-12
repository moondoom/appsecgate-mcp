SERVER_DIR     := mcp-server
IMAGE          ?= appsecgate/mcp
VERSION        ?= 0.1.0
NAMESPACE      ?= appsecgate
TAG            ?= animage/appsecgate-mcp:$(VERSION)
PROJECT_PATH   ?= $(CURDIR)
WITH_JAVA_DB   ?= false

.PHONY: help setup test lint format check \
        docker-build docker-run docker-down docker-push \
        clean

help: ## Показать список основных команд
	@echo "Основные цели:"
	@echo "  setup        Установить зависимости через uv (включая dev)"
	@echo "  test         Запустить тесты"
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
	cd $(SERVER_DIR) && uv run ruff format src tests

check: lint test ## Полная проверка перед коммитом

docker-build: ## Собрать Docker-образ (context = mcp-server)
	docker build \
	  --build-arg WITH_JAVA_DB=$(WITH_JAVA_DB) \
	  -t $(TAG) \
	  -f $(SERVER_DIR)/Dockerfile \
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