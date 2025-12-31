#!/bin/bash
# E2E Demo Application Runner
# This script sets up the environment and runs the Flask demo app

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

echo "Syncing dependencies with e2e extras..."
cd "$PROJECT_ROOT"
uv sync --extra e2e

echo "Starting Flask demo app on port ${PORT:-5001}..."
cd "$SCRIPT_DIR"
exec uv run --project "$PROJECT_ROOT" --extra e2e python -m flask --app run:app run --host 0.0.0.0 --port "${PORT:-5001}"
