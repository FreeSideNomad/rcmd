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

### 5. Using Batches

Batches group related commands together and track their collective progress. Use batches when you need to:
- Track completion of multiple related commands
- Get notified when all commands in a group complete
- Monitor success/failure rates for a set of operations

```python
from uuid import uuid4
from commandbus import CommandBus, BatchCommand, BatchMetadata

async def process_monthly_billing(bus: CommandBus, accounts: list[dict]) -> UUID:
    """Create a batch of billing commands with completion callback."""

    # Define callback for when batch completes
    async def on_batch_complete(batch: BatchMetadata) -> None:
        print(f"Batch {batch.batch_id} finished:")
        print(f"  - Completed: {batch.completed_count}/{batch.total_count}")
        print(f"  - Failed: {batch.in_troubleshooting_count}")
        print(f"  - Status: {batch.status.value}")

    # Create batch with commands
    result = await bus.create_batch(
        domain="billing",
        commands=[
            BatchCommand(
                command_type="ProcessPayment",
                command_id=uuid4(),
                data={"account_id": acc["id"], "amount": acc["balance"]},
            )
            for acc in accounts
        ],
        name="Monthly billing - January 2026",
        on_complete=on_batch_complete,  # Called when all commands finish
    )

    print(f"Created batch {result.batch_id} with {result.total_commands} commands")
    return result.batch_id


async def monitor_batch(bus: CommandBus, batch_id: UUID) -> None:
    """Poll batch status for progress monitoring."""
    batch = await bus.get_batch("billing", batch_id)
    if batch:
        progress = (batch.completed_count + batch.in_troubleshooting_count) / batch.total_count
        print(f"Batch progress: {progress:.1%}")
        print(f"  Status: {batch.status.value}")
        print(f"  Completed: {batch.completed_count}")
        print(f"  In TSQ: {batch.in_troubleshooting_count}")
```

**Batch Status Lifecycle:**
- `PENDING` → Batch created, commands waiting to be processed
- `IN_PROGRESS` → At least one command has started processing
- `COMPLETED` → All commands completed successfully
- `COMPLETED_WITH_FAILURES` → All commands finished, some failed (in TSQ)

**Note:** Batch callbacks are in-memory only and will be lost on worker restart. For critical workflows, poll `get_batch()` as a fallback

## E2E Test Application

The repository includes an end-to-end test application with a web UI for testing command processing with **probabilistic behaviors**.

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

### Probabilistic Behavior Model

Commands use a **probabilistic behavior model** with configurable outcome percentages:

| Parameter | Description |
|-----------|-------------|
| `fail_permanent_pct` | Chance of permanent failure (0-100%) |
| `fail_transient_pct` | Chance of transient failure (0-100%) |
| `timeout_pct` | Chance of timeout behavior (0-100%) |
| `min_duration_ms` | Minimum execution time (ms) |
| `max_duration_ms` | Maximum execution time (ms) |

**Evaluation Order:** Probabilities are evaluated sequentially - permanent failure first, then transient, then timeout. If none trigger, the command succeeds with execution time sampled from a normal distribution between min and max duration.

**Example Configurations:**

| Scenario | Settings |
|----------|----------|
| **Pure throughput test** | All percentages 0%, duration 0ms |
| **Realistic workload** | 1% permanent, 5% transient, 100-500ms duration |
| **High failure rate** | 10% permanent, 20% transient |
| **Stress test retries** | 50% transient failure rate |

### Outcome Calculator

The UI includes an **Expected Outcomes Calculator** that shows predicted results based on your probability settings:

```
For 10,000 commands with 2% permanent, 8% transient:
├── ~200 permanent failures → TSQ immediately
├── ~800 transient failures → Retry (some recover)
└── ~9,000 succeed on first attempt
```

### Bulk Generation

For load testing, use the bulk generation form:
1. Adjust probability sliders for desired failure rates
2. Set execution time range (0ms for maximum throughput)
3. Set count (up to 1,000,000)
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
