# S017 - Base Infrastructure Setup

## Parent Feature
F006 - E2E Testing & Demo Application

## User Story

**As a** developer
**I want** the foundational infrastructure for the E2E demo application
**So that** I can build UI views and automated tests on top of it

## Context

This story sets up the Flask application structure, database migrations, test_command model, worker implementation, and base UI layout. All subsequent stories depend on this infrastructure.

## Acceptance Criteria

### Scenario: Flask application starts
**Given** the E2E app dependencies are installed
**When** I run `python tests/e2e/run.py`
**Then** Flask starts on port 5001
**And** the home page loads with sidebar navigation

### Scenario: Database migrations run
**Given** PostgreSQL is running with commandbus_e2e database
**When** I run Flyway migrations
**Then** command_bus_command, command_bus_audit, PGMQ queues, and test_command tables exist

### Scenario: Worker processes test commands
**Given** a test command with behavior "success" exists
**When** the worker receives the command
**Then** it looks up behavior from test_command table
**And** completes the command successfully

### Scenario: Worker handles behavior types
**Given** test commands with various behaviors exist
**When** the worker processes them
**Then** `success` → completes normally
**And** `fail_permanent` → raises PermanentCommandError
**And** `fail_transient` → raises TransientCommandError
**And** `fail_transient_then_succeed` → fails N times then succeeds
**And** `timeout` → sleeps to simulate timeout

## Technical Implementation

### Files to Create

```
tests/e2e/
├── app/
│   ├── __init__.py          # create_app factory
│   ├── config.py            # E2E database URL, settings
│   ├── models.py            # TestCommand SQLAlchemy model
│   ├── worker.py            # Worker with behavior handler
│   ├── web/
│   │   ├── __init__.py
│   │   └── routes.py        # Serves base HTML pages
│   ├── static/
│   │   ├── src/
│   │   │   ├── input.css    # Tailwind directives
│   │   │   └── api.js       # Fetch wrapper
│   │   └── dist/            # Generated (gitignored)
│   └── templates/
│       ├── layouts/
│       │   └── base.html    # Flowbite sidebar layout
│       ├── includes/
│       │   ├── navbar.html
│       │   └── sidebar.html
│       └── pages/
│           └── dashboard.html  # Placeholder
├── migrations/
│   ├── V001__commandbus_schema.sql
│   ├── V002__pgmq_queues.sql
│   └── V003__test_command_table.sql
├── requirements.txt
├── tailwind.config.js
├── flyway.conf
└── run.py
```

### Database Schema (V003)

```sql
CREATE TABLE test_command (
    id SERIAL PRIMARY KEY,
    command_id UUID NOT NULL UNIQUE,
    payload JSONB NOT NULL DEFAULT '{}',
    behavior JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    attempts INTEGER DEFAULT 0,
    result JSONB
);

CREATE INDEX idx_test_command_command_id ON test_command(command_id);
```

### Worker Behavior Handler

```python
@registry.handler("test", "TestCommand")
async def handle_test_command(cmd: Command, ctx: HandlerContext) -> dict:
    behavior = await lookup_behavior(cmd.command_id)

    # Track attempt
    await increment_attempt(cmd.command_id)
    attempt = await get_attempt_count(cmd.command_id)

    # Simulate execution time (applies to all behaviors)
    execution_time_ms = behavior.get("execution_time_ms", 0)
    if execution_time_ms > 0:
        await asyncio.sleep(execution_time_ms / 1000)

    match behavior["type"]:
        case "success":
            return {"status": "success"}
        case "fail_permanent":
            raise PermanentCommandError(
                code=behavior.get("error_code", "PERMANENT"),
                message=behavior.get("error_message", "Simulated permanent failure")
            )
        case "fail_transient":
            raise TransientCommandError(
                code=behavior.get("error_code", "TRANSIENT"),
                message=behavior.get("error_message", "Simulated transient failure")
            )
        case "fail_transient_then_succeed":
            if attempt <= behavior.get("transient_failures", 1):
                raise TransientCommandError(
                    code="TRANSIENT",
                    message=f"Transient failure {attempt}"
                )
            return {"status": "success", "attempts": attempt}
        case "timeout":
            # For timeout behavior, execution_time_ms should be > visibility_timeout
            # The command will time out and be redelivered
            return {"status": "success"}
```

### Configuration Management

The app stores and exposes worker/retry configuration:

```python
# tests/e2e/app/config.py

@dataclass
class WorkerConfig:
    visibility_timeout: int = 30      # seconds
    concurrency: int = 4
    poll_interval: float = 1.0        # seconds
    batch_size: int = 10

@dataclass
class RetryConfig:
    max_attempts: int = 3
    base_delay_ms: int = 1000
    max_delay_ms: int = 60000
    backoff_multiplier: float = 2.0

# Configuration is stored in database and editable via UI
class ConfigStore:
    async def get_worker_config(self) -> WorkerConfig: ...
    async def set_worker_config(self, config: WorkerConfig) -> None: ...
    async def get_retry_config(self) -> RetryConfig: ...
    async def set_retry_config(self, config: RetryConfig) -> None: ...
```

## Definition of Done

- [ ] Flask app starts and serves base layout with sidebar
- [ ] Flyway migrations create all required tables (including config table)
- [ ] TestCommand model with CRUD operations
- [ ] Worker processes commands based on behavior specification
- [ ] All behavior types implemented and tested manually
- [ ] Configuration store for worker/retry settings
- [ ] Settings page in UI to view/edit configuration
- [ ] Tailwind CSS compiles correctly
- [ ] requirements.txt with all dependencies
- [ ] README with setup instructions

## Story Size
L (5000-10000 tokens)

## Priority
Must Have

## Dependencies
- PostgreSQL with PGMQ extension running
- commandbus library available
