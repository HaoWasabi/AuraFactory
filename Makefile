# AuraFactory — Makefile
# Usage: make <target>

.PHONY: setup dev test db-reset docker-up docker-down lint clean help

# Default target
help:
	@echo "AuraFactory Development Commands"
	@echo "================================="
	@echo "  make setup       - Install dependencies + create dirs"
	@echo "  make dev         - Run development server (uvicorn reload)"
	@echo "  make test        - Run test suite"
	@echo "  make db-reset    - Reset database (drop + recreate)"
	@echo "  make docker-up   - Start all services via docker-compose"
	@echo "  make docker-down - Stop all docker services"
	@echo "  make lint        - Run linter (ruff)"
	@echo "  make clean       - Remove cache and temp files"

# Setup project
setup:
	pip install -r requirements.txt
	mkdir -p data/knowledge logs/traces frontend/static
	@echo "✅ Setup complete. Copy .env.example to .env and configure."

# Development server (with reload)
dev:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Run tests
test:
	python -m pytest tests/ -v --tb=short

# Reset database
db-reset:
	@echo "⚠️  Dropping and recreating database..."
	docker exec aurafactory-db psql -U aurafactory -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
	@echo "✅ Database reset complete."

# Docker compose up
docker-up:
	docker-compose up -d --build
	@echo "✅ Services started. App: http://localhost:8000"

# Docker compose down
docker-down:
	docker-compose down -v
	@echo "✅ Services stopped."

# Lint code
lint:
	ruff check app/ --fix
	ruff format app/

# Clean temp files
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache
	@echo "✅ Cleaned."
