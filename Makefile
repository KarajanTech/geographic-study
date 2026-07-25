SHELL := /bin/bash
API_DIR := apps/api
UV_RUN := uv run --project $(API_DIR)
COMPOSE := docker compose

# Database-backed tests use this URL and skip themselves when it is unreachable.
# Read from .env when present so `make test` needs no extra setup.
TEST_DATABASE_URL ?= $(shell grep -E '^SENTINEL_TEST_DATABASE_URL=' .env 2>/dev/null | cut -d= -f2-)

.DEFAULT_GOAL := help
.PHONY: help install dev up down logs ps dev-api dev-web dev-worker \
        fmt fmt-check lint typecheck test test-cov check ci \
        schemas schemas-check db-upgrade db-revision db-test-create \
        sample-dem demo-project clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# --- Setup --------------------------------------------------------------------

install: ## Install Python and Node dependencies
	uv sync --project $(API_DIR)
	npm install

# --- Running ------------------------------------------------------------------

dev: ## Start database, API and web with Docker Compose
	$(COMPOSE) up --build

up: ## Start the stack in the background
	$(COMPOSE) up -d --build

down: ## Stop the stack (data volume is kept)
	$(COMPOSE) down

logs: ## Follow container logs
	$(COMPOSE) logs -f

ps: ## Show container status
	$(COMPOSE) ps

dev-api: ## Run the API on the host with reload
	$(UV_RUN) uvicorn app.main:app --reload --app-dir $(API_DIR) --port 8000

dev-web: ## Run the web app on the host
	npm run dev --workspace @sentinel/web

dev-worker: ## Run the viewshed worker on the host
	cd $(API_DIR) && uv run python -m app.workers.viewshed_worker

# --- Quality ------------------------------------------------------------------

fmt: ## Format Python and TypeScript
	$(UV_RUN) ruff format .
	npm run format

fmt-check: ## Verify formatting without writing
	$(UV_RUN) ruff format --check .
	npm run format:check

lint: ## Lint Python and TypeScript
	$(UV_RUN) ruff check .
	npm run lint

typecheck: ## Type check Python and TypeScript
	cd $(API_DIR) && uv run mypy
	MYPYPATH=$(API_DIR) $(UV_RUN) mypy --config-file $(API_DIR)/pyproject.toml scripts
	npm run typecheck

test: ## Run the API test suite (database tests skip without a test database)
	cd $(API_DIR) && SENTINEL_TEST_DATABASE_URL="$(TEST_DATABASE_URL)" uv run pytest

test-cov: ## Run tests with a coverage report
	cd $(API_DIR) && SENTINEL_TEST_DATABASE_URL="$(TEST_DATABASE_URL)" \
		uv run pytest --cov=app --cov-report=term-missing

check: fmt-check lint typecheck test ## Everything CI runs

ci: check schemas-check ## CI entry point

# --- Schemas ------------------------------------------------------------------

schemas: ## Export OpenAPI and regenerate the shared TypeScript types
	$(UV_RUN) python scripts/export_openapi.py
	npm run schemas:generate

schemas-check: ## Fail when the committed schemas drift from the API
	@$(MAKE) --no-print-directory schemas
	@git diff --exit-code -- packages/shared-schemas \
		|| (echo "Shared schemas are stale. Run 'make schemas' and commit the result." && exit 1)

# --- Database -----------------------------------------------------------------

db-upgrade: ## Apply database migrations
	cd $(API_DIR) && uv run alembic upgrade head

db-revision: ## Create a migration: make db-revision m="add projects"
	cd $(API_DIR) && uv run alembic revision --autogenerate -m "$(m)"

db-test-create: ## Create the PostGIS database used by the test suite
	$(COMPOSE) exec -T db psql -U $${POSTGRES_USER:-sentinel} -d postgres \
		-c "CREATE DATABASE sentinel_test OWNER $${POSTGRES_USER:-sentinel}" || true
	$(COMPOSE) exec -T db psql -U $${POSTGRES_USER:-sentinel} -d sentinel_test \
		-c "CREATE EXTENSION IF NOT EXISTS postgis"

# --- Data ---------------------------------------------------------------------

sample-dem: ## Generate the synthetic sample DEM in data/raw
	$(UV_RUN) python scripts/make_sample_dem.py --force

demo-project: ## Create a demo project and ingest a synthetic DEM through the API
	$(UV_RUN) python scripts/seed_demo_project.py

# --- Housekeeping -------------------------------------------------------------

clean: ## Remove caches and build artefacts
	rm -rf $(API_DIR)/.pytest_cache $(API_DIR)/.mypy_cache $(API_DIR)/.ruff_cache
	rm -rf apps/web/.next apps/web/tsconfig.tsbuildinfo
	find . -name __pycache__ -type d -prune -not -path "*/node_modules/*" -exec rm -rf {} +
