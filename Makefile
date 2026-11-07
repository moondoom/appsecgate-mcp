SERVER_DIR     := mcp-server
MASTER_DIR     := appsecgate-master
AGENT_DIR      := appsecgate-agent
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
        agent-setup agent-lint agent-test agent-format \
        docker-build docker-run docker-down docker-push docker-master-build \
        compose-up compose-down compose-edge-sync \
        clean

help: ## Показать список основных команд
	@echo "Основные цели:"
	@echo "  setup          Установить зависимости всех пакетов (uv, incl. dev)"
	@echo "  test           Запустить тесты mcp-server"
	@echo "  test-file      Запустить один файл (make test-file FILE=tests/test_server_smoke.py)"
	@echo "  lint           Проверить код mcp-server ruff'ом"
	@echo "  format         Отформатировать mcp-server ruff'ом"
	@echo "  master-setup   Установить зависимости appsecgate-master (uv)"
	@echo "  master-test    Запустить тесты appsecgate-master"
	@echo "  master-lint    Проверить код appsecgate-master ruff'ом"
	@echo "  master-format  Отформатировать appsecgate-master ruff'ом"
	@echo "  agent-test     Запустить тесты appsecgate-agent"
	@echo "  agent-lint     Проверить код appsecgate-agent ruff'ом"
	@echo "  agent-format   Отформатировать appsecgate-agent ruff'ом"
	@echo "  check          Полная проверка всех пакетов (lint + test)"
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
	cd $(AGENT_DIR) && uv sync --extra dev

master-setup: ## Установить зависимости appsecgate-master через uv
	cd $(MASTER_DIR) && uv sync --extra dev

agent-setup: ## Установить зависимости appsecgate-agent через uv
	cd $(AGENT_DIR) && uv sync --extra dev

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

agent-test: ## Запустить тесты appsecgate-agent
	cd $(AGENT_DIR) && uv run pytest

agent-lint: ## Проверить код appsecgate-agent ruff'ом
	cd $(AGENT_DIR) && uv run ruff check src tests

agent-format: ## Отформатировать код appsecgate-agent ruff'ом
	cd $(AGENT_DIR) && uv run ruff check --fix src tests
	cd $(AGENT_DIR) && uv run ruff format src tests

test-file: ## Запустить один тестовый файл (FILE=tests/test_server_smoke.py)
	@test -n "$(FILE)" || (echo "Укажите FILE=путь/к/тесту.py" && exit 1)
	cd $(SERVER_DIR) && uv run pytest $(FILE)

check: lint test master-lint master-test agent-lint agent-test ## Полная проверка всех пакетов

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

compose-postgres-up: ## Поднять master с PostgreSQL (ADR-0012)
	docker compose -f docker-compose.yml -f docker-compose.postgres.yml up -d master

compose-postgres-down: ## Остановить master и PostgreSQL
	docker compose -f docker-compose.yml -f docker-compose.postgres.yml down

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

SMOKE_KEYS = {"pygoat-tp0001-agent-dev-v1-gemmaq3-t01":"smoke-t01-key","pygoat-tp0001-agent-dev-v1-gemmaq3-t04":"smoke-t04-key","pygoat-tp0001-agent-dev-v1-gemmaq3-t07":"smoke-t07-key","agent-dev-knowledge":"agent-dev-knowledge-key"}

experiment-master-up: ## Поднять изолированный master для agent smoke на порту 8001
	docker rm -f appsecgate-agent-smoke-master >/dev/null 2>&1 || true
	docker network inspect appsecgate-mcp_appsecgate >/dev/null 2>&1 || \
		docker network create appsecgate-mcp_appsecgate
	docker run --rm -d --name appsecgate-agent-smoke-master \
		--network appsecgate-mcp_appsecgate \
		-p 127.0.0.1:8001:8000 \
		-e APPSECGATE_MASTER_API_KEYS='$(SMOKE_KEYS)' \
		-e APPSECGATE_MASTER_DB=/tmp/agent-smoke-master.db \
		$(MASTER_TAG)

experiment-master-down: ## Остановить изолированный agent smoke master
	docker stop appsecgate-agent-smoke-master >/dev/null 2>&1 || true

experiment-mock-llm: ## Запустить deterministic OpenAI-compatible mock для agent smoke
	cd experiments/tp-0001 && python3 mock_llm.py --port 4001

experiment-gate-smoke: ## Прогнать autonomous agent T-01/T-04/T-07 через mock LLM
	cd experiments/tp-0001 && APPSECGATE_MASTER_API_KEYS='$(SMOKE_KEYS)' \
		APPSECGATE_MASTER_URL=http://appsecgate-agent-smoke-master:8000 \
		APPSECGATE_MASTER_HOST_URL=http://127.0.0.1:8001 \
		GATE_PREFIX=agent-dev-v1 GATE_KEY_PREFIX=agent-dev-v1 \
		TESTS="t01 t04 t07" APPSECGATE_LLM_MODEL=mock-gate \
		bash gate_tests/run_cycle.sh gemmaq3
	cd experiments/tp-0001 && GATE_PREFIX=agent-dev-v1 TESTS="t01 t04 t07" \
		python3 gate_tests/evaluate.py gemmaq3

experiment-collect-smoke: ## Собрать funnel и review из smoke-отчётов
	cd experiments/tp-0001 && python3 collect_agent_funnel.py --label agent-dev-v1 \
		--pattern 'artifacts/agent-dev-v1-gemmaq3-*/report.json' \
		--prefix agent-dev-v1-smoke

experiment-master-knowledge: ## Загрузить human-confirmed development knowledge на smoke master
	cd experiments/tp-0001 && python3 prepare_master_knowledge.py

experiment-dev-run: ## Запустить настоящий gemmaq3 на DEV_PROJECTS (development corpus)
	cd experiments/tp-0001 && APPSECGATE_MASTER_URL= APPSECGATE_MASTER_API_KEY= NO_SYNC=1 \
		APPSECGATE_NO_MASTER_KNOWLEDGE=1 \
		DOCKER_NETWORK=bridge BENCH_MODELS=$(or $(BENCH_MODELS),gemmaq3) BENCH_PARALLELISM=$(or $(PARALLELISM),1) \
		BENCH_PROJECTS=$(or $(DEV_PROJECTS),aitextgen) \
		BENCH_LABEL=$(or $(DEV_LABEL),agent-dev-v1) \
		BENCH_OUTPUT=$(or $(DEV_LABEL),agent-dev-v1)-benchmark.json \
		python3 benchmark_parallel.py

experiment-dev-wait: ## Дождаться исходных development containers CodeWiki и zep
	docker wait appsecgate-agent-dev-v2-gemmaq3-p2-CodeWiki \
		appsecgate-agent-dev-v2-gemmaq3-p2-zep

experiment-corpus-prepare: ## Подготовить 300 репозиториев и agent300-manifest.json
	cd experiments/tp-0001 && python3 prepare_agent_corpus.py

experiment-agent300-master: ## Поднять master со всеми project keys для 300
	cd experiments/tp-0001 && python3 start_agent_master.py

experiment-semgrep-rules-prepare: ## Скачать оптимизированные внешние Semgrep-правила для 300
	mcp-server/.venv/bin/appsecgate-mcp rules install \
		--data-dir experiments/tp-0001/runtime/research-rules \
		--source semgrep --source trailofbits --profile agent300 --accept-licenses

experiment-semgrep-rules-validate: ## Проверить внешние правила в существующем образе
	docker run --rm --read-only --network none --tmpfs /tmp:size=100M \
		-e SEMGREP_SETTINGS_FILE=/tmp/semgrep-settings.yml \
		-e SEMGREP_VERSION_CACHE_PATH=/tmp/semgrep-version \
		--entrypoint semgrep \
		-v $(CURDIR)/experiments/tp-0001/runtime/research-rules/rules:/research-rules:ro \
		$(TAG) scan --json --quiet --metrics=off --disable-version-check \
		--config /opt/appsecgate/rules/opengrep-community \
		--config /opt/appsecgate/rules/semgrep-custom \
		--config /research-rules/external-semgrep \
		--config /research-rules/external-trailofbits \
		/opt/appsecgate/rules/semgrep-custom/appsecgate-base.yaml
	docker run --rm --read-only --network none --tmpfs /tmp:size=100M \
		-e APPSECGATE_RULES_DISTRIBUTION_MODE=commercial \
		--entrypoint /opt/appsecgate-venv/bin/python \
		-v $(CURDIR)/experiments/tp-0001/runtime/research-rules/rules:/home/appsecgate/.appsecgate-mcp/rules:ro \
		-v $(CURDIR)/projects/juice-shop:/workspace:ro \
		$(TAG) -c \
		"from appsecgate_mcp.config.loader import ConfigLoader; c = ConfigLoader().load('/workspace'); ids = {b.id for b in c.resolved_rules.bundles}; assert {'external/semgrep', 'external/trailofbits'} <= ids; print(c.resolved_rules.ruleset_hash, sorted(ids))"

experiment-run-config: ## Сформировать frozen run config и project keys для 300
	cd experiments/tp-0001 && python3 prepare_agent_run_config.py

experiment-cve-prepare: ## Сформировать и импортировать замороженный OSV snapshot
	cd experiments/tp-0001 && python3 prepare_cve_snapshot.py $(CVE_ARGS)
	docker cp experiments/tp-0001/runtime/cve-input.json \
		appsecgate-agent300-master:/tmp/cve-input.json
	docker exec appsecgate-agent300-master \
		python -m appsecgate_master.cve_ingest /tmp/cve-input.json

experiment-readiness-check: ## Проверить готовность 300 без запуска основного корпуса
	cd experiments/tp-0001 && python3 check_agent_readiness.py

experiment-agent300-preflight: ## Запустить preflight 300 без sync для CVE manifest
	cd experiments/tp-0001 && RESEARCH_SEMGREP_RULES=1 python3 run_agent300.py --label agent300-preflight --no-sync

experiment-agent300-run: ## Запустить замороженный основной корпус 300
	cd experiments/tp-0001 && RESEARCH_SEMGREP_RULES=1 python3 run_agent300.py --label agent300

experiment-agent300-repeat: ## Повторить 10 development репозиториев для стабильности
	cd experiments/tp-0001 && RESEARCH_SEMGREP_RULES=1 python3 run_agent300.py --label agent300repeat

experiment-reevaluation-run: ## Прогнать REV-1 на 10 repos с baseline project identity
	cd experiments/tp-0001 && RESEARCH_SEMGREP_RULES=1 python3 run_agent300.py --label agent300review

experiment-reevaluation-stats: ## Собрать TTL/confidence/provenance статистику 10 review runs
	cd experiments/tp-0001 && python3 collect_reevaluation_stats.py

experiment-rev1-validation: ## Controlled Phase A/B/C: fresh, expired и legacy reuse
	cd experiments/tp-0001 && RESEARCH_SEMGREP_RULES=1 python3 validate_rev1.py

experiment-adr18-run: ## Прогнать ADR-0018 Mode A на 10 repos (label agent300adr18)
	cd experiments/tp-0001 && RESEARCH_SEMGREP_RULES=1 python3 run_agent300.py --label agent300adr18

experiment-fix1-run: ## Прогнать 10 repos с фиксом quote_hash/parallelism (label agent300fix1)
	cd experiments/tp-0001 && RESEARCH_SEMGREP_RULES=1 python3 run_agent300.py --label agent300fix1

experiment-adr18-stats: ## Собрать categorical статистику ADR-0018 Mode A
	cd experiments/tp-0001 && python3 collect_adr18_stats.py

experiment-fix1-stats: ## Собрать статистику фикс-серии против agent300adr18
	cd experiments/tp-0001 && STATS_LABEL=agent300fix1 STATS_BASELINE=agent300adr18 python3 collect_adr18_stats.py

experiment-rev1-operations: ## Разобрать bitcore, AIWriteX и duplicate fingerprints
	cd experiments/tp-0001 && python3 analyze_rev1_operations.py

experiment-adr18-operations: ## Разобрать bitcore/AIWriteX/dedup для серии agent300adr18
	cd experiments/tp-0001 && OPS_LABEL=agent300adr18 python3 analyze_rev1_operations.py

experiment-confidence-review: ## Подготовить 100 findings для ручной confidence calibration
	cd experiments/tp-0001 && python3 prepare_confidence_review.py

experiment-adr18-review: ## Слепой categorical review bundle для серии agent300adr18
	cd experiments/tp-0001 && python3 prepare_adr18_review.py

experiment-kv-probe: ## Экспресс-проба ollama: контекст × параллельность (PROBE_TAG=q4 для повтора)
	cd experiments/tp-0001 && python3 kv_probe.py

experiment-preflight: ## GD-11 fail-fast preflight: slot budget, model digest, Prometheus metrics
	cd experiments/tp-0001 && python3 preflight.py --output artifacts/preflight-$(shell date +%Y%m%d-%H%M%S).json

experiment-funnel-cost: ## Воронка × токены по серии runs (LABEL=accb|...)
	cd experiments/tp-0001 && python3 collect_funnel_cost.py --label $(LABEL)

experiment-sweep-summary: ## GD-7 sweep analysis: гейты G1-G5 + gpu-per-arm + failure breakdown
	cd experiments/tp-0001 && python3 collect_sweep_summary.py

experiment-cve-signals: ## GD-12: deterministic CVE signals vs verdicts (measurement only)
	cd experiments/tp-0001 && python3 measure_cve_signals.py

clean: ## Удалить локальные артефакты uv всех пакетов
	cd $(SERVER_DIR) && rm -rf .venv .pytest_cache .ruff_cache
	cd $(MASTER_DIR) && rm -rf .venv .pytest_cache .ruff_cache
	cd $(AGENT_DIR) && rm -rf .venv .pytest_cache .ruff_cache