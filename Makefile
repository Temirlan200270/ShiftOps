# ShiftOps Makefile — common developer commands.
# Note: PowerShell users can run `make` via `make.exe` from chocolatey or use
# the equivalent docker compose commands directly.

COMPOSE := docker compose -f infra/docker-compose.yml --env-file .env

.PHONY: help dev up down logs ps restart api web seed migrate revision \
        test test-api test-web lint lint-api lint-web fmt clean install

help: ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

dev: up logs ## Boot the full stack and tail logs.

up: ## Start the stack in the background.
	$(COMPOSE) up -d --build

down: ## Stop the stack.
	$(COMPOSE) down

logs: ## Tail logs.
	$(COMPOSE) logs -f --tail=100

ps: ## Show running services.
	$(COMPOSE) ps

restart: down up ## Restart everything.

api: ## Open a shell inside the API container.
	$(COMPOSE) exec api bash

web: ## Open a shell inside the web container.
	$(COMPOSE) exec web sh

seed: ## Seed demo organization, locations, users, templates.
	$(COMPOSE) exec api python -m scripts.seed

migrate: ## Apply latest Alembic migrations.
	$(COMPOSE) exec api alembic upgrade head

revision: ## Generate a new Alembic migration. Usage: make revision m="add foo"
	$(COMPOSE) exec api alembic revision --autogenerate -m "$(m)"

test: test-api test-web ## Run all tests.

test-api:
	$(COMPOSE) exec api pytest -q

test-web:
	$(COMPOSE) exec web pnpm vitest run

lint: lint-api lint-web ## Run all linters.

lint-api:
	$(COMPOSE) exec api ruff check .
	$(COMPOSE) exec api ruff format --check .

lint-web:
	$(COMPOSE) exec web pnpm lint

fmt: ## Format code (ruff + prettier).
	$(COMPOSE) exec api ruff format .
	$(COMPOSE) exec web pnpm format

install: ## Install local dev dependencies (host machine, no docker).
	cd apps/api && uv sync
	cd apps/web && pnpm install

clean: ## Remove containers and volumes.
	$(COMPOSE) down -v
