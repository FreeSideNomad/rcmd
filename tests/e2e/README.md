# E2E Testing & Demo Application

A FastAPI-based demo application for testing and demonstrating the commandbus library.

## Quick Start

### 1. Database Setup

Create the E2E database:

```bash
createdb commandbus_e2e
```

Run Flyway migrations:

```bash
# Using Flyway CLI
flyway -configFiles=flyway.conf migrate

# Or manually run the SQL files
psql commandbus_e2e < migrations/V001__pgmq_extension.sql
psql commandbus_e2e < migrations/V002__commandbus_schema.sql
psql commandbus_e2e < migrations/V003__pgmq_queues.sql
psql commandbus_e2e < migrations/V004__test_command_table.sql
```

### 2. Install Dependencies

```bash
# From the project root
pip install -e .

# Install E2E app dependencies
pip install -r tests/e2e/requirements.txt
```

### 3. Run the Application

```bash
cd tests/e2e
python run.py
```

The app will be available at http://localhost:5001

### 4. Run the Worker

In a separate terminal:

```bash
cd tests/e2e
python -m app.worker
```

## Tailwind CSS

To rebuild the CSS (requires tailwindcss CLI):

```bash
# Download tailwindcss CLI
curl -sLO https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-macos-arm64
chmod +x tailwindcss-macos-arm64
mv tailwindcss-macos-arm64 tailwindcss

# Build CSS
./tailwindcss -i ./app/static/src/input.css -o ./app/static/dist/output.css

# Watch for changes during development
./tailwindcss -i ./app/static/src/input.css -o ./app/static/dist/output.css --watch
```

## Features

- **Dashboard**: Overview of command processing status
- **Send Command**: Create test commands with configurable behaviors
- **Commands Browser**: View and filter all commands
- **Troubleshooting Queue**: Manage failed commands
- **Audit Trail**: View command event history
- **Settings**: Configure worker and retry parameters

## Test Command Behaviors

| Behavior | Description |
|----------|-------------|
| `success` | Completes successfully after execution_time_ms |
| `fail_permanent` | Throws PermanentCommandError, moves to TSQ |
| `fail_transient` | Throws TransientCommandError, retries until exhausted |
| `fail_transient_then_succeed` | Fails N times, then succeeds |
| `timeout` | Sleeps for execution_time_ms (for testing visibility timeout) |

## Configuration

All configuration is stored in the `e2e.config` table and editable via the Settings page:

### Worker Configuration
- `visibility_timeout`: How long before unacknowledged message is redelivered (default: 30s)
- `concurrency`: Number of concurrent command processors (default: 4)
- `poll_interval`: How often to poll queue (default: 1s)
- `batch_size`: Messages to fetch per poll (default: 10)

### Retry Configuration
- `max_attempts`: Maximum retry attempts before TSQ (default: 3)
- `base_delay_ms`: Base delay for exponential backoff (default: 1000ms)
- `max_delay_ms`: Maximum delay between retries (default: 60000ms)
- `backoff_multiplier`: Multiplier for exponential backoff (default: 2.0)
