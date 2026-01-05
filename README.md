# rcmd - Reliable Commands

[![PyPI version](https://img.shields.io/pypi/v/reliable-cmd)](https://pypi.org/project/reliable-cmd/)
[![Python Versions](https://img.shields.io/pypi/pyversions/reliable-cmd)](https://pypi.org/project/reliable-cmd/)
[![License: MIT](https://img.shields.io/pypi/l/reliable-cmd)](https://opensource.org/licenses/MIT)

A Python library providing Command Bus abstraction over PostgreSQL + PGMQ.

## Installation

```bash
pip install reliable-cmd
```

## Overview

Command Bus enables reliable command processing with:

- **At-least-once delivery** via PGMQ visibility timeout
- **Transactional guarantees** - commands sent atomically with business data
- **Retry policies** with configurable backoff
- **Troubleshooting queue** for failed commands with operator actions
- **Audit trail** for all state transitions

## Requirements

- Python 3.11+
- PostgreSQL 15+ with [PGMQ extension](https://github.com/tembo-io/pgmq)

## Quick Start

### 1. Database Setup

First, ensure you have PostgreSQL with PGMQ extension installed. Then set up the commandbus schema:

```python
import asyncio
from psycopg_pool import AsyncConnectionPool
from commandbus import setup_database

async def main():
    pool = AsyncConnectionPool(
        conninfo="postgresql://user:pass@localhost:5432/mydb"  # pragma: allowlist secret
    )
    await pool.open()

    # Create commandbus schema, tables, and stored procedures
    created = await setup_database(pool)
    if created:
        print("Database schema created successfully")
    else:
        print("Schema already exists")

    await pool.close()

asyncio.run(main())
```

The `setup_database()` function is idempotent - it safely skips if the schema already exists.

### 2. Alternative: Manual SQL Setup

If you prefer to manage migrations separately (e.g., with Flyway or Alembic), you can get the raw SQL:

```python
from commandbus import get_schema_sql

sql = get_schema_sql()
# Execute this SQL in your migration tool
```

Or copy the SQL file from the installed package:
```bash
python -c "from commandbus import get_schema_sql; print(get_schema_sql())" > schema.sql
```

## Developer Guide

This section covers how to set up command handlers and configure workers for your domain.

### 1. Define Command Handlers

Use the `@handler` decorator to mark methods as command handlers. Handlers are organized in classes with constructor-injected dependencies:

```python
from psycopg_pool import AsyncConnectionPool
from commandbus import Command, HandlerContext, handler

class OrderHandlers:
    """Handlers for order domain commands."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Inject dependencies via constructor."""
        self._pool = pool

    @handler(domain="orders", command_type="CreateOrder")
    async def handle_create_order(
        self, cmd: Command, ctx: HandlerContext
    ) -> dict[str, Any]:
        """Handle CreateOrder command.

        Args:
            cmd: The command with command_id and data
            ctx: Handler context (currently provides metadata)

        Returns:
            Result dict stored in command record
        """
        order_data = cmd.data
        # Process the order...
        return {"status": "created", "order_id": str(cmd.command_id)}

    @handler(domain="orders", command_type="CancelOrder")
    async def handle_cancel_order(
        self, cmd: Command, ctx: HandlerContext
    ) -> dict[str, Any]:
        """Handle CancelOrder command."""
        # Cancel logic...
        return {"status": "cancelled"}
```

### 2. Handle Errors

Use built-in exception types to control retry behavior:

```python
from commandbus.exceptions import PermanentCommandError, TransientCommandError

@handler(domain="orders", command_type="ProcessPayment")
async def handle_payment(self, cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
    try:
        result = await payment_gateway.process(cmd.data)
        return {"status": "paid", "transaction_id": result.id}
    except PaymentDeclined as e:
        # Permanent failure - no retry, moves to troubleshooting queue
        raise PermanentCommandError(
            code="PAYMENT_DECLINED",
            message=str(e)
        )
    except GatewayTimeout as e:
        # Transient failure - will be retried according to policy
        raise TransientCommandError(
            code="GATEWAY_TIMEOUT",
            message=str(e)
        )
```

### 3. Register Handlers and Create Worker

Create a composition root that wires up dependencies and registers handlers:

```python
from psycopg_pool import AsyncConnectionPool
from commandbus import HandlerRegistry, RetryPolicy, Worker

async def create_pool() -> AsyncConnectionPool:
    pool = AsyncConnectionPool(
        conninfo="postgresql://localhost:5432/mydb",  # configure auth as needed
        min_size=2,
        max_size=10,
    )
    await pool.open()
    return pool

def create_registry(pool: AsyncConnectionPool) -> HandlerRegistry:
    """Create registry and register all handlers."""
    # Create handler instances with dependencies
    order_handlers = OrderHandlers(pool)
    inventory_handlers = InventoryHandlers(pool)

    # Register handlers - decorator metadata is used for routing
    registry = HandlerRegistry()
    registry.register_instance(order_handlers)
    registry.register_instance(inventory_handlers)

    return registry

def create_worker(pool: AsyncConnectionPool) -> Worker:
    """Create worker with retry policy."""
    registry = create_registry(pool)

    retry_policy = RetryPolicy(
        max_attempts=3,
        backoff_schedule=[10, 60, 300],  # seconds between retries
    )

    return Worker(
        pool=pool,
        domain="orders",
        registry=registry,
        retry_policy=retry_policy,
        visibility_timeout=30,  # seconds before message redelivery
    )

async def run_worker() -> None:
    """Main entry point."""
    pool = await create_pool()
    try:
        worker = create_worker(pool)
        await worker.run(
            concurrency=4,      # concurrent command handlers
            poll_interval=1.0,  # seconds between queue polls
        )
    finally:
        await pool.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_worker())
```

### 4. Send Commands

Use the `CommandBus` to send commands:

```python
from uuid import uuid4
from commandbus import CommandBus

async def create_order(bus: CommandBus, order_data: dict) -> UUID:
    command_id = uuid4()

    await bus.send(
        domain="orders",
        command_type="CreateOrder",
        command_id=command_id,
        data=order_data,
        max_attempts=3,  # optional, overrides retry policy
    )

    return command_id
```

For high-throughput scenarios, use batch sending:

```python
from commandbus.models import SendRequest

requests = [
    SendRequest(
        domain="orders",
        command_type="CreateOrder",
        command_id=uuid4(),
        data={"product_id": "123", "quantity": 1},
    )
    for _ in range(1000)
]

result = await bus.send_batch(requests)
print(f"Sent {result.total_commands} commands in {result.chunks_processed} chunks")
```

## E2E Test Application

The repository includes an end-to-end test application with a web UI for testing command processing behaviors.

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ with dependencies installed (see Quick Start)

### Running the E2E Application

**1. Start the database:**

```bash
make docker-up
```

**2. Start the web UI:**

```bash
make e2e-app
```

The web UI is available at http://localhost:5001

**3. Start workers (in a separate terminal):**

```bash
cd tests/e2e
python -m app.worker
```

To run multiple workers for load testing:

```bash
cd tests/e2e
for i in {1..4}; do
  python -m app.worker &
done
```

### Test Behaviors

The E2E UI supports various command behaviors for testing:

| Behavior | Description |
|----------|-------------|
| **No-Op** | Returns immediately, for throughput benchmarking |
| **Success** | Completes successfully after optional delay |
| **Fail Permanent** | Fails with PermanentCommandError, moves to TSQ |
| **Fail Transient** | Fails with TransientCommandError, retries |
| **Fail Transient Then Succeed** | Fails N times, then succeeds |
| **Timeout** | Simulates slow execution |

### Bulk Generation

For load testing, use the bulk generation form:
1. Select behavior type (No-Op recommended for pure throughput tests)
2. Set count (up to 1,000,000)
3. Set execution time (0ms for maximum throughput)
4. Click "Generate Bulk Commands"

### Monitoring

The E2E UI provides:
- **Dashboard**: Real-time status counts and throughput metrics
- **Commands**: List and filter commands by status
- **Troubleshooting Queue**: View and action failed commands
- **Audit Trail**: Full event history per command

## Documentation

- [Implementation Spec](docs/command-bus-python-spec.md) - Detailed design and API
- [Architecture Decisions](docs/architecture/adr/) - ADRs explaining key choices
- [Contributing](CONTRIBUTING.md) - How to contribute

## License

MIT
