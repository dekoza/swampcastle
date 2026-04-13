.PHONY: test test-unit test-integration test-e2e test-build test-down

test-unit: ## Run fast unit tests on host
	uv run pytest tests/ \
		--ignore=tests/benchmarks \
		-k 'not TestSyncServer and not test_detect_rooms_local_interactive' \
		-m 'not integration and not postgres' -x

test-integration: ## Run PostgreSQL integration tests in Docker
	docker compose -f compose.test.yml run --rm tests \
		pytest tests/integration/ -m 'integration and postgres' -x

test-e2e: ## No E2E suite for this library project
	@echo "No E2E tests for this library project"

test: test-unit test-integration ## Run unit + integration tests

test-build: ## Build Docker-based test image
	docker compose -f compose.test.yml build

test-down: ## Tear down Docker-based test environment
	docker compose -f compose.test.yml down -v
