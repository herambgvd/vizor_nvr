# =============================================================================
# GVD NVR — convenience targets
# =============================================================================
# Run `make help` for the full list.

COMPOSE_FILES_PROD = -f docker-compose.yml
COMPOSE_FILES_DEV  = -f docker-compose.yml -f docker-compose.dev.yml

.DEFAULT_GOAL := help

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make <target>\n\nTargets:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

up: ## Start full stack (production-mode)
	bash scripts/seed-go2rtc-config.sh
	docker compose $(COMPOSE_FILES_PROD) up -d

dev: ## Start full stack with hot reload (bind-mounts source)
	bash scripts/seed-go2rtc-config.sh
	docker compose $(COMPOSE_FILES_DEV) up -d

down: ## Stop all services
	docker compose $(COMPOSE_FILES_PROD) down

restart: ## Restart all services
	docker compose $(COMPOSE_FILES_PROD) restart

logs: ## Tail backend logs
	docker compose logs -f backend

logs-fe: ## Tail frontend logs (dev mode)
	docker compose logs -f frontend

build: ## Rebuild backend + frontend images
	docker compose build backend frontend

migrate: ## Apply Alembic migrations
	docker compose exec backend alembic upgrade head

shell: ## Open a Python shell inside backend
	docker compose exec backend python

psql: ## Open psql against the Vizor database
	docker exec -it gvd_db psql -U nvr -d gvd_nvr

ps: ## Show container status
	docker compose ps
