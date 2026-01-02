#!/bin/bash
# E2E Demo Application Runner
# This script sets up the environment and runs the Flask demo app
#
# Recommended: Use 'make e2e-app' from the project root instead.
#
# Prerequisites:
#   1. Start database: make docker-up
#   2. Set up E2E tables: make e2e-setup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$SCRIPT_DIR"

# Check if .env exists, if not copy from example
if [ ! -f ".env" ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

# Load environment variables
set -a
source .env
set +a

# Check if uv is available
if ! command -v uv &> /dev/null; then
    echo "Error: uv not found. Please install uv first."
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Check if Docker is running and postgres is up
if ! docker compose -f "$PROJECT_ROOT/docker-compose.yml" ps postgres 2>/dev/null | grep -q "Up"; then
    echo "Warning: PostgreSQL container not running."
    echo "  Run 'make docker-up' from project root first."
    echo ""
fi

echo "Syncing dependencies with e2e extras..."
cd "$PROJECT_ROOT"
uv sync --extra e2e

echo ""
echo "Starting Flask demo app on http://localhost:${PORT:-5001}"
echo "Tip: Run 'make e2e-setup' if you see database errors."
echo ""
cd "$SCRIPT_DIR"
exec uv run --project "$PROJECT_ROOT" --extra e2e python -m flask --app run:app run --host 0.0.0.0 --port "${PORT:-5001}"
