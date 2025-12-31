# F006 - E2E Testing & Demo Application

## Overview

A Flask-based demo application and E2E testing framework that provides:
1. **Automated E2E Tests**: Comprehensive end-to-end tests for the commandbus library
2. **Interactive Demo UI**: Visual interface for exploring commandbus functionality
3. **Load Testing Support**: Ability to generate and process large command volumes

## Architecture

```
tests/e2e/
├── app/                      # Flask Demo Application
│   ├── __init__.py          # App factory
│   ├── config.py            # Configuration
│   ├── models.py            # TestCommand model
│   ├── worker.py            # Command processor worker
│   ├── api/                 # JSON API endpoints
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── web/                 # HTML page routes
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── static/
│   │   ├── dist/            # Generated CSS (gitignored)
│   │   ├── src/
│   │   │   ├── input.css    # Tailwind directives
│   │   │   └── api.js       # AJAX client
│   │   └── js/              # Page-specific scripts
│   └── templates/
│       ├── layouts/
│       │   └── base.html
│       ├── includes/
│       │   ├── navbar.html
│       │   └── sidebar.html
│       └── pages/
│           ├── dashboard.html
│           ├── send_command.html
│           ├── commands.html
│           ├── troubleshooting.html
│           └── audit.html
├── migrations/              # Flyway SQL migrations
│   ├── V001__commandbus_schema.sql
│   ├── V002__pgmq_queues.sql
│   └── V003__test_command_table.sql
├── tests/                   # Automated E2E tests
│   ├── conftest.py
│   ├── test_success_scenarios.py
│   ├── test_transient_failure.py
│   ├── test_permanent_failure.py
│   ├── test_retry_exhaustion.py
│   ├── test_timeout.py
│   └── test_tsq_operations.py
├── requirements.txt         # E2E app dependencies
├── tailwind.config.js
└── run.py                   # Entry point
```

## Test Command Behavior Specification

The `test_command` table stores command payloads with behavior instructions:

```sql
CREATE TABLE test_command (
    id SERIAL PRIMARY KEY,
    command_id UUID NOT NULL UNIQUE,
    payload JSONB NOT NULL,
    behavior JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    result JSONB
);
```

### Behavior JSON Schema

```json
{
  "type": "success" | "fail_permanent" | "fail_transient" | "fail_transient_then_succeed" | "timeout",
  "transient_failures": 2,           // Number of transient failures before success
  "execution_time_ms": 100,          // How long command execution takes
  "error_code": "INVALID_DATA",      // For failure behaviors
  "error_message": "Simulated error" // For failure behaviors
}
```

### Behavior Types

| Type | Description | Expected Outcome |
|------|-------------|------------------|
| `success` | Completes after execution_time_ms | COMPLETED status |
| `fail_permanent` | Throws PermanentCommandError after execution_time_ms | Moves to TSQ |
| `fail_transient` | Throws TransientCommandError indefinitely | Exhausts retries → TSQ |
| `fail_transient_then_succeed` | Fails N times then succeeds | COMPLETED after N+1 attempts |
| `timeout` | Sleeps for execution_time_ms (set > visibility_timeout) | Re-delivered, eventually succeeds |

## Configurable Parameters

The UI exposes all worker and retry configuration parameters for experimentation:

### Worker Configuration
| Parameter | Default | Description |
|-----------|---------|-------------|
| `visibility_timeout` | 30s | How long before unacknowledged message is redelivered |
| `concurrency` | 4 | Number of concurrent command processors |
| `poll_interval` | 1s | How often to poll queue when using polling mode |
| `batch_size` | 10 | Number of messages to fetch per poll |

### Retry Configuration
| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_attempts` | 3 | Maximum retry attempts before TSQ |
| `base_delay_ms` | 1000 | Base delay for exponential backoff |
| `max_delay_ms` | 60000 | Maximum delay between retries |
| `backoff_multiplier` | 2.0 | Multiplier for exponential backoff |

### Command Behavior
| Parameter | Description |
|-----------|-------------|
| `execution_time_ms` | How long the command handler takes to execute |
| `transient_failures` | Number of transient failures before success |
| `error_code` | Error code for failure behaviors |
| `error_message` | Error message for failure behaviors |

## UI Views

### 1. Dashboard
- Overview statistics (pending, in-progress, completed, failed, in TSQ)
- Quick actions to send test commands

### 2. Send Command
- Form to create test commands with behavior configuration
- Bulk command generation for load testing (generate N commands)

### 3. Commands Browser
- Filter by: status, domain, command_type, date range
- Pagination with configurable page size
- View command details and audit trail

### 4. Troubleshooting Queue
- List commands in TSQ with error details
- Action buttons: Retry, Cancel, Complete
- Bulk operations support

### 5. Audit Trail
- Search by command_id
- Chronological event display
- Event details expansion

## Worker Architecture

The worker processes commands from the queue and executes behavior based on the test_command specification:

```python
@handler("test", "TestCommand")
async def handle_test_command(cmd: Command, ctx: HandlerContext) -> dict:
    # 1. Lookup behavior from test_command table
    behavior = await get_command_behavior(cmd.command_id)

    # 2. Execute behavior
    if behavior["type"] == "success":
        return {"status": "ok"}
    elif behavior["type"] == "fail_permanent":
        raise PermanentCommandError(
            code=behavior.get("error_code", "PERMANENT_ERROR"),
            message=behavior.get("error_message", "Simulated permanent failure")
        )
    # ... etc
```

### Concurrent Workers

Multiple workers can be started for load testing:

```bash
# Start 4 concurrent workers
python -m tests.e2e.app.worker --concurrency 4

# Or multiple processes
for i in {1..4}; do
    python -m tests.e2e.app.worker &
done
```

## Database Configuration

The E2E app uses a separate database to avoid conflicts with integration tests:

```
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/commandbus_e2e  # pragma: allowlist secret
```

## Technology Stack

- **Backend**: Python 3.11+, Flask 3.x, Flask-SQLAlchemy
- **Frontend**: Tailwind CSS (standalone CLI), Flowbite, Vanilla JS
- **Database**: PostgreSQL 15+ with PGMQ extension
- **Migrations**: Flyway

## Dependencies

```
# E2E App specific (in addition to commandbus)
Flask>=3.1.0
Flask-SQLAlchemy>=3.1.1
python-dotenv>=1.0.1
```

## User Stories

| Story | Description | Priority |
|-------|-------------|----------|
| S017 | Base Infrastructure Setup | Must Have |
| S018 | Send Command View | Must Have |
| S019 | Commands Browser View | Must Have |
| S020 | Troubleshooting Queue View | Must Have |
| S021 | Audit Trail View | Should Have |
| S022 | Dashboard View | Should Have |
| S023 | Automated E2E Tests - Success Scenarios | Must Have |
| S024 | Automated E2E Tests - Failure Scenarios | Must Have |
| S025 | Load Testing Support | Could Have |

## Success Criteria

1. All automated E2E tests pass
2. UI provides full visibility into command lifecycle
3. TSQ operations (retry, cancel, complete) work correctly
4. Multiple concurrent workers can process commands
5. Load test can generate and process 10,000+ commands
