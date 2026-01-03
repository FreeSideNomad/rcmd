#!/bin/bash
# E2E Worker Runner
# Starts the worker that processes commands from the e2e__commands queue
#
# Usage:
#   ./run-worker.sh           # Start a worker (kills existing workers first)
#   ./run-worker.sh --no-kill # Start additional worker without killing existing ones
#
# To run multiple workers in parallel:
#   ./run-worker.sh &         # Start first worker
#   ./run-worker.sh --no-kill & # Start additional workers
#
# Prerequisites:
#   1. Start database: make docker-up
#   2. Set up E2E tables: make e2e-setup
#   3. Start the demo app: make e2e-app (or ./run-demo.sh)

set -e

# Parse arguments
SKIP_KILL=false
for arg in "$@"; do
    case $arg in
        --no-kill)
            SKIP_KILL=true
            shift
            ;;
    esac
done

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

# Stop any existing worker processes (unless --no-kill flag is passed)
if [ "$SKIP_KILL" = false ]; then
    EXISTING_PIDS=$(pgrep -f "python -m app.worker" 2>/dev/null || true)
    if [ -n "$EXISTING_PIDS" ]; then
        echo "Stopping existing worker processes..."
        echo "$EXISTING_PIDS" | xargs kill 2>/dev/null || true
        sleep 1
        echo "Stopped."
    fi
fi

echo "Syncing dependencies with e2e extras..."
cd "$PROJECT_ROOT"
uv sync --extra e2e

echo ""
echo "Starting E2E worker..."
echo "Registered handler: e2e.TestCommand"
echo ""
echo "The worker will process commands from the e2e__commands queue."
echo "Create commands via the web UI at http://localhost:5001/send-command"
echo ""

cd "$SCRIPT_DIR"
exec uv run --project "$PROJECT_ROOT" --extra e2e python -m app.worker
