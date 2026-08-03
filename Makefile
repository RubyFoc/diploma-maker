SHELL := /bin/bash

.PHONY: help env compose-config up rebuild clean-orphans down down-v ps logs smoke backend-lint backend-test frontend-lint frontend-test

help:
	@echo "Available targets:"
	@echo "  make up            # create .env if missing and start stack"
	@echo "  make rebuild       # rebuild images and force recreate containers"
	@echo "  make clean-orphans # remove orphan containers without full teardown"
	@echo "  make down          # stop stack"
	@echo "  make down-v        # stop stack and remove volumes + orphans"
	@echo "  make ps            # show compose services status"
	@echo "  make logs          # follow compose logs"
	@echo "  make smoke         # run local smoke checks"
	@echo "  make compose-config # validate compose config"
	@echo "  make backend-lint  # ruff check backend"
	@echo "  make backend-test  # pytest backend"
	@echo "  make frontend-lint # eslint frontend"
	@echo "  make frontend-test # vitest frontend"

env:
	@if [ ! -f .env ]; then cp .env.example .env; fi

compose-config:
	@docker compose config -q

up: env
	@docker compose up -d --build

rebuild: env
	@docker compose up -d --build --force-recreate

clean-orphans: env
	@docker compose up -d --remove-orphans

down:
	@docker compose down

down-v:
	@docker compose down -v --remove-orphans

ps:
	@docker compose ps

logs:
	@docker compose logs -f --tail=200

smoke:
	@./scripts/smoke-compose.sh

backend-lint:
	@uv run --project apps/backend ruff check .

backend-test:
	@uv run --project apps/backend pytest -q

frontend-lint:
	@npm --prefix apps/frontend run lint

frontend-test:
	@npm --prefix apps/frontend run test
