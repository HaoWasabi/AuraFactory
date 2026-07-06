# Makefile — AuraFactory v3.0 Development Commands
.PHONY: help install run dev db-up db-down clean test lint format

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# === Setup ===
install: ## Install Python dependencies
	pip install -r requirements.txt

# === Run ===
run: ## Run the application (production mode)
	python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

dev: ## Run with auto-reload (development)
	python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

main: ## Run via main.py directly (shows banner)
	python -m app.main

# === Docker ===
db-up: ## Start PostgreSQL in Docker
	docker-compose up -d postgres

db-down: ## Stop PostgreSQL
	docker-compose down

docker-up: ## Start all services
	docker-compose up -d

docker-down: ## Stop all services
	docker-compose down

docker-logs: ## View application logs
	docker-compose logs -f app

# === Code Quality ===
lint: ## Run linter (ruff)
	ruff check app/ --fix

format: ## Format code (black)
	black app/ --line-length=100

test: ## Run tests
	pytest tests/ -v

test-cov: ## Run tests with coverage
	pytest tests/ --cov=app --cov-report=html

# === Utilities ===
clean: ## Remove __pycache__ and temp files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache htmlcov .coverage

tree: ## Show project structure
	tree app/ -I __pycache__ --dirsfirst

# === Database ===
db-migrate: ## Run database migrations (placeholder)
	@echo "TODO: Alembic migrations"

db-reset: ## Reset database
	docker-compose exec postgres psql -U aurafactory -c "DROP DATABASE IF EXISTS aurafactory; CREATE DATABASE aurafactory;"
