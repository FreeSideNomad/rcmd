.PHONY: help install install-dev lint format typecheck test test-unit test-integration test-e2e coverage docker-up docker-down clean ready e2e-app e2e-setup

# Default target
help:
	@echo "Command Bus Development Tasks"
	@echo ""
	@echo "Setup:"
	@echo "  make install        Install production dependencies"
	@echo "  make install-dev    Install all dependencies including dev tools"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint           Run linter (ruff check)"
	@echo "  make format         Format code (ruff format)"
	@echo "  make typecheck      Run type checker (mypy)"
	@echo "  make check          Run all quality checks"
	@echo "  make ready          Run all checks before commit (format + lint + typecheck + test)"
	@echo ""
	@echo "Testing:"
	@echo "  make test           Run all tests"
	@echo "  make test-unit      Run unit tests only"
	@echo "  make test-integration  Run integration tests (requires Docker)"
	@echo "  make test-e2e       Run end-to-end tests (requires Docker)"
	@echo "  make coverage       Run tests with coverage report"
	@echo "  make test-coverage  Check coverage >= 80% (pre-commit hook)"
	@echo "  make coverage-html  Generate and open HTML coverage report"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-up      Start PostgreSQL + PGMQ containers"
	@echo "  make docker-down    Stop and remove containers"
	@echo "  make docker-logs    Show container logs"
	@echo ""
	@echo "E2E Demo:"
	@echo "  make e2e-setup      Set up E2E database (run after docker-up)"
	@echo "  make e2e-app        Start E2E demo application on http://localhost:5001"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean          Remove build artifacts and caches"
	@echo "  make build          Build distribution packages"

# =============================================================================
# Setup
# =============================================================================

install:
	uv sync --no-dev

install-dev:
	uv sync --all-extras
	uv run pre-commit install

# =============================================================================
# Code Quality
# =============================================================================

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests
	uv run ruff check --fix src tests

typecheck:
	uv run mypy src

check: lint typecheck
	@echo "All checks passed!"

# Run all checks before commit - use this before every git commit
# Includes integration tests if Docker postgres is running
ready: format lint typecheck test-coverage
	@if docker compose ps postgres 2>/dev/null | grep -q "Up"; then \
		echo "Docker postgres is running, running integration tests..."; \
		uv run pytest tests/integration -v -m integration || exit 1; \
	else \
		echo "⚠️  Docker postgres not running, skipping integration tests (run 'make docker-up' to enable)"; \
	fi
	@echo ""
	@echo "✅ All checks passed! Ready to commit."

# =============================================================================
# Testing
# =============================================================================

test:
	uv run pytest tests -v

test-unit:
	uv run pytest tests/unit -v

test-integration:
	uv run pytest tests/integration -v -m integration

test-e2e:
	uv run pytest tests/e2e -v -m e2e

coverage:
	uv run pytest tests --cov=src/commandbus --cov-report=html --cov-report=term-missing
	@echo "Coverage report: htmlcov/index.html"

# Check coverage meets 80% threshold (used by pre-commit hook)
test-coverage:
	uv run pytest tests/unit --cov=src/commandbus --cov-branch --cov-fail-under=80 -q
	@echo "Coverage check passed (>= 80%)"

# Generate HTML coverage report
coverage-html:
	uv run pytest tests --cov=src/commandbus --cov-branch --cov-report=html --cov-report=term
	@echo "HTML report: htmlcov/index.html"
	@open htmlcov/index.html 2>/dev/null || xdg-open htmlcov/index.html 2>/dev/null || echo "Open htmlcov/index.html in browser"

# Run a specific test file
# Usage: make test-file FILE=tests/unit/test_api.py
test-file:
	uv run pytest $(FILE) -v

# =============================================================================
# Docker
# =============================================================================

docker-up:
	docker compose up -d
	@echo "Waiting for PostgreSQL to be ready..."
	@sleep 3
	@docker compose exec -T postgres pg_isready -U postgres || (echo "PostgreSQL not ready" && exit 1)
	@echo "PostgreSQL is ready!"
	@echo "Waiting for Flyway migrations to complete..."
	@docker compose logs flyway --follow 2>&1 | head -50 || true
	@echo "Database initialized with Flyway migrations!"

docker-down:
	docker compose down -v

docker-logs:
	docker compose logs -f

docker-psql:
	docker compose exec postgres psql -U postgres -d commandbus

# =============================================================================
# E2E Demo Application
# =============================================================================

# Set up E2E database tables and queues (run after docker-up if using fresh DB)
e2e-setup:
	@echo "E2E database is now set up automatically via Flyway migrations (V002__e2e_schema.sql)"
	@echo "Run 'make docker-up' to start PostgreSQL with migrations applied"

# Start the E2E demo application
e2e-app:
	@echo "Starting E2E Demo Application..."
	@echo "Open http://localhost:5001 in your browser"
	cd tests/e2e && uv run python run.py

# =============================================================================
# Build & Release
# =============================================================================

build:
	uv build

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# =============================================================================
# Development Helpers
# =============================================================================

# Generate a new migration
# Usage: make migration NAME=add_status_column
migration:
	@echo "Creating migration: $(NAME)"
	@mkdir -p src/commandbus/migrations
	@touch "src/commandbus/migrations/$$(date +%Y%m%d%H%M%S)_$(NAME).sql"
	@echo "Created: src/commandbus/migrations/$$(date +%Y%m%d%H%M%S)_$(NAME).sql"

# Create a new ADR
# Usage: make adr NAME=use-redis-for-caching
adr:
	@NEXT=$$(ls docs/architecture/adr/*.md 2>/dev/null | grep -E '^docs/architecture/adr/[0-9]{3}' | wc -l | tr -d ' '); \
	NEXT=$$((NEXT + 1)); \
	PADDED=$$(printf "%03d" $$NEXT); \
	FILE="docs/architecture/adr/$${PADDED}-$(NAME).md"; \
	cp docs/architecture/adr/template.md "$$FILE"; \
	sed -i '' "s/ADR-NNN/ADR-$${PADDED}/" "$$FILE" 2>/dev/null || sed -i "s/ADR-NNN/ADR-$${PADDED}/" "$$FILE"; \
	echo "Created: $$FILE"

# Watch for changes and run tests
watch:
	uv run pytest-watch tests/unit -- -v

# Pre-commit checks (run before committing)
pre-commit:
	uv run pre-commit run --all-files
