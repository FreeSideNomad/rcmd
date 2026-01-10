# rcmd - Reliable Commands

[![PyPI version](https://img.shields.io/pypi/v/reliable-cmd)](https://pypi.org/project/reliable-cmd/)
[![Python Versions](https://img.shields.io/pypi/pyversions/reliable-cmd)](https://pypi.org/project/reliable-cmd/)
[![License: MIT](https://img.shields.io/pypi/l/reliable-cmd)](https://opensource.org/licenses/MIT)

A Python library providing Command Bus abstraction over PostgreSQL + PGMQ for reliable, durable command processing.

## Table of Contents

- [Why Reliable Commands?](#why-reliable-commands)
- [Ubiquitous Language](#ubiquitous-language)
- [Architecture Overview](#architecture-overview)
- [Command Lifecycle](#command-lifecycle)
- [PGMQ Integration](#pgmq-integration)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Synchronous Usage](#synchronous-usage)
- [Developer Guide](#developer-guide)
  - [Using Reply Queues](#6-using-reply-queues)
- [Worker Best Practices](#worker-best-practices)
- [E2E Test Application](#e2e-test-application)

---

## Release Highlights

### v0.2.0 - Native Synchronous Runtime

- **Native sync implementation.** Complete rewrite of synchronous components using psycopg3's native `ConnectionPool` (sync) instead of async wrappers. `SyncWorker` now uses `ThreadPoolExecutor` for true thread-based concurrency without event loop overhead.
- **2.4x throughput improvement.** Batch processing performance increased from ~250/s to ~610/s through on-demand batch stats calculation, eliminating hot row contention on the batch table.
- **Dual runtime toggle.** The FastAPI E2E app, worker CLI, and API dependencies honor the async vs sync runtime stored in `/settings`, with logs showing `Runtime mode: ...` and guidance to restart workers after saving.
- **Linear scaling for I/O-bound workloads.** With the native sync implementation, workers scale near-linearly: 5 workers achieve ~640 commands/sec for 200ms latency tasks (vs ~190/s with 1 worker).
- **Operator playbook.** The [E2E test plan](docs/e2e-test-plan.md#module-runtime-toggle-ts-runtime) documents how to flip modes, restart services, send verification commands, inspect TSQ, and toggle back.

---

## Why Reliable Commands?

In distributed systems, ensuring that operations complete reliably is challenging. Consider these common problems:

### The Lost Update Problem

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Client    │────▶│   Service   │────▶│  External   │
│             │     │             │     │    API      │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                    ❌ Crash here
                           │
                    Data saved to DB
                    but API never called
```

When your service crashes between saving data and calling an external API, you end up with inconsistent state.

### The Dual-Write Problem

```python
# DANGEROUS: Two separate operations, no atomicity
await db.save(order)           # ✓ Succeeds
await email_service.send(...)  # ❌ Fails - but order is already saved!
```

### The Solution: Reliable Command Queue

Reliable Commands provides a **durable command queue** backed by PostgreSQL:

```
┌─────────────────────────────────────────────────────────┐
│                    PostgreSQL                           │
│                                                         │
│  ┌─────────────────┐    ┌─────────────────┐             │
│  │ Command Metadata│    │  PGMQ Queue     │             │
│  │  (commandbus.   │    │  (msg_id,       │             │
│  │   command)      │    │   payload)      │             │
│  └────────┬────────┘    └────────┬────────┘             │
│           │                      │                      │
│           └──────────┬───────────┘                      │
│                      │                                  │
│          Written atomically together                    │
└──────────────────────┼──────────────────────────────────┘
                       │
                       ▼
               ┌───────────────┐
               │    Worker     │
               │  (separate    │
               │   process)    │
               └───────────────┘
```

**Benefits:**
- **Durability**: Commands persist in PostgreSQL until processed
- **At-least-once delivery**: Failed commands are automatically retried
- **Visibility timeout**: Commands redelivered if worker crashes
- **Observability**: Full audit trail of all state transitions

---

## Ubiquitous Language

Understanding these terms is essential for working with the library:

### Core Concepts

| Term | Definition |
|------|------------|
| **Command** | A request to perform an action. Immutable once created. Contains a unique ID, type, and payload data. |
| **Domain** | A logical grouping of related commands (e.g., "orders", "payments", "inventory"). Each domain has its own queue. |
| **Handler** | An async function that processes a specific command type. Registered via the `@handler` decorator. |
| **Worker** | A long-running process that polls for commands and dispatches them to handlers. |

### State & Lifecycle

| Term | Definition |
|------|------------|
| **Pending** | Command is queued and waiting to be processed. |
| **In Progress** | Worker has claimed the command and handler is executing. |
| **Completed** | Handler returned successfully. Terminal state. |
| **Failed** | Handler raised an error. May be retried or moved to TSQ. |
| **Troubleshooting Queue (TSQ)** | Holds commands that exhausted retries or had permanent failures. Requires operator intervention. |

### Reliability Mechanisms

| Term | Definition |
|------|------------|
| **Visibility Timeout** | How long a worker has to process a command before it becomes visible to other workers again. Prevents message loss if a worker crashes. |
| **Retry Policy** | Rules for how many times and how often to retry failed commands. |
| **Backoff Schedule** | Increasing delays between retry attempts (e.g., 10s, 60s, 300s). |
| **Transient Error** | Temporary failure (network timeout, database lock). Command will be retried. |
| **Permanent Error** | Unrecoverable failure (invalid data, business rule violation). Command goes directly to TSQ. |

### Batches & Correlation

| Term | Definition |
|------|------------|
| **Batch** | A group of related commands tracked together. Useful for bulk operations. |
| **Correlation ID** | Links related commands across a workflow. Useful for tracing. |
| **Audit Event** | Immutable record of a state change. Provides complete history. |

### Reply Queues

| Term | Definition |
|------|------------|
| **Reply Queue** | A PGMQ queue where command results are sent after processing. Enables async request-reply patterns. |
| **Reply To** | The queue name specified when sending a command. If set, the worker sends results there on completion. |
| **Reply Outcome** | The result status: `SUCCESS`, `FAILED`, or `CANCELED`. |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              Your Application                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌──────────────┐         ┌──────────────────────────────────────┐     │
│   │  CommandBus  │         │              Worker                  │     │
│   │              │         │  ┌────────────────────────────────┐  │     │
│   │  .send()     │         │  │        HandlerRegistry         │  │     │
│   │  .send_batch │         │  │  ┌──────────┐  ┌──────────┐    │  │     │
│   │  .get_batch  │         │  │  │ Handler  │  │ Handler  │    │  │     │
│   │              │         │  │  │ @orders  │  │ @payments│    │  │     │
│   └──────┬───────┘         │  │  └──────────┘  └──────────┘    │  │     │
│          │                 │  └────────────────────────────────┘  │     │
│          │                 └──────────────────┬───────────────────┘     │
│          │                                    │                         │
└──────────┼────────────────────────────────────┼─────────────────────────┘
           │                                    │
           ▼                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                            PostgreSQL + PGMQ                            │
│                                                                         │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐          │
│  │  commandbus.    │  │    pgmq.        │  │  commandbus.    │          │
│  │    command      │  │  q_<domain>     │  │    audit        │          │
│  │                 │  │                 │  │                 │          │
│  │  - command_id   │  │  - msg_id       │  │  - event_type   │          │
│  │  - status       │  │  - payload      │  │  - timestamp    │          │
│  │  - attempts     │  │  - vt (visible) │  │  - details      │          │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘          │
│                                                                         │
│  ┌─────────────────┐  ┌─────────────────┐                               │
│  │  commandbus.    │  │  commandbus.    │                               │
│  │    batch        │  │    tsq          │                               │
│  │                 │  │                 │                               │
│  │  - batch_id     │  │  - Failed       │                               │
│  │  - total_count  │  │    commands     │                               │
│  │  - completed    │  │    for review   │                               │
│  └─────────────────┘  └─────────────────┘                               │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Command Lifecycle

### State Machine

```
                                    ┌────────────────────────────────┐
                                    │                                │
                                    ▼                                │
┌─────────┐    ┌─────────────┐    ┌─────────┐    ┌───────────┐       │
│ PENDING │───▶│ IN_PROGRESS │───▶│ FAILED  │───▶│  PENDING  │───────┘
└─────────┘    └──────┬──────┘    └────┬────┘    └───────────┘
                      │                │          (retry with backoff)
                      │                │
                      ▼                ▼
               ┌───────────┐    ┌─────────────┐
               │ COMPLETED │    │     TSQ     │
               │  (final)  │    │   (final)   │
               └───────────┘    └─────────────┘
```

### State Transitions

| From | To | Trigger |
|------|----|---------|
| — | PENDING | `bus.send()` or `bus.create_batch()` |
| PENDING | IN_PROGRESS | Worker receives message from queue |
| IN_PROGRESS | COMPLETED | Handler returns successfully |
| IN_PROGRESS | FAILED | Handler raises exception |
| FAILED | PENDING | Transient error + retries remaining |
| FAILED | TSQ | Permanent error OR retries exhausted |

### Visibility Timeout Flow

```
Time ──────────────────────────────────────────────────────────────▶

Worker A claims message (VT = now + 30s)
     │
     ├─────────── Processing ───────────┤
     │                                  │
     │                          Worker A completes
     │                          Message deleted ✓
     │
     │
Alternative: Worker A crashes
     │
     ├─────────── Processing ───────────┤
     │                                  │
     X  Worker A dies                   │
                                        │
                              ┌─────────┴─────────┐
                              │  VT expires       │
                              │  Message visible  │
                              │  again            │
                              └─────────┬─────────┘
                                        │
                              Worker B claims message
                              Processing continues...
```

---

## PGMQ Integration

### What is PGMQ?

[PGMQ](https://github.com/tembo-io/pgmq) is a lightweight message queue built as a PostgreSQL extension. It provides:

- **Transactional enqueue**: Messages are only visible after commit
- **Visibility timeout**: Claimed messages are invisible to other consumers
- **Delivery guarantees**: Messages persist until explicitly deleted

### How rcmd Uses PGMQ

When you call `bus.send()`, rcmd creates a single transaction that:
1. Inserts command metadata into `commandbus.command`
2. Sends a message to the PGMQ queue
3. Records an audit event

```
┌─────────────────────────────────────────────────────────────────┐
│                    CommandBus.send() Transaction                 │
│                                                                  │
│   BEGIN;                                                         │
│                                                                  │
│   -- Insert command metadata                                     │
│   INSERT INTO commandbus.command (command_id, status, ...)      │
│                                                                  │
│   -- Queue the message                                           │
│   SELECT pgmq.send('orders__commands', '{"type": "...", ...}'); │
│                                                                  │
│   -- Record audit event                                          │
│   INSERT INTO commandbus.audit (event_type, ...)                │
│                                                                  │
│   COMMIT;  ◀── All three succeed or all fail                     │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Queue Naming Convention

Each domain gets its own PGMQ queue with the naming pattern `{domain}__commands`:

| Domain | Queue Name |
|--------|------------|
| `orders` | `orders__commands` |
| `payments` | `payments__commands` |
| `inventory` | `inventory__commands` |

### Message Flow

```
Producer                           PGMQ                           Consumer
   │                                │                                │
   │  pgmq.send(queue, payload)     │                                │
   ├───────────────────────────────▶│                                │
   │                                │                                │
   │                                │◀─── pgmq.read(queue, vt=30) ───┤
   │                                │                                │
   │                                │     Returns message + msg_id   │
   │                                ├───────────────────────────────▶│
   │                                │                                │
   │                                │     (invisible for 30s)        │
   │                                │                                │
   │                                │◀─── pgmq.delete(queue, id) ────┤
   │                                │                                │
   │                                │     (on success)               │
   │                                │                                │
```

### LISTEN/NOTIFY for Low Latency

Instead of constant polling, rcmd uses PostgreSQL's LISTEN/NOTIFY:

```
┌──────────────┐                    ┌──────────────┐
│   Producer   │                    │    Worker    │
└──────┬───────┘                    └──────┬───────┘
       │                                   │
       │  INSERT + NOTIFY                  │  LISTEN q_orders
       ├──────────────────────────────────▶│
       │                                   │
       │                                   │  Immediate wake-up!
       │                                   │  (no polling delay)
       │                                   │
```

---

## Installation

```bash
pip install reliable-cmd
```

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

---

## Synchronous Usage

Reliable Commands provides **native synchronous support** for teams using blocking frameworks (Flask, Django, CLI tools). The `commandbus.sync` package uses psycopg3's native sync `ConnectionPool` and `ThreadPoolExecutor` for true thread-based concurrency—no async wrappers or event loops involved.

```python
from uuid import uuid4

from psycopg_pool import ConnectionPool  # Note: sync ConnectionPool, not AsyncConnectionPool
from commandbus import Command, HandlerRegistry, handler

from commandbus.sync import SyncCommandBus, SyncWorker


class PaymentHandlers:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    @handler(domain="payments", command_type="DebitAccount")
    def handle(self, cmd: Command, ctx):  # Sync handler - no async/await
        # Blocking handler logic
        with self._pool.connection() as conn:
            conn.execute("UPDATE accounts SET balance = balance - %s WHERE id = %s",
                        (cmd.data["amount"], cmd.data["account_id"]))
        return {"status": "ok"}


# Create sync connection pool (sized for worker concurrency)
pool = ConnectionPool(
    conninfo="postgresql://postgres:postgres@localhost:5432/commandbus",  # pragma: allowlist secret
    min_size=4,   # At least equal to worker concurrency
    max_size=8,   # 2x min_size is a good default
    timeout=30.0, # Fail-fast on pool exhaustion
)
pool.open()  # Sync open - no await

# Send commands synchronously
bus = SyncCommandBus(pool)
result = bus.send(
    domain="payments",
    command_type="DebitAccount",
    command_id=uuid4(),
    data={"account_id": "123", "amount": 100},
)

# Create and run sync worker
registry = HandlerRegistry()
registry.register_instance(PaymentHandlers(pool))

worker = SyncWorker(
    pool=pool,
    domain="payments",
    registry=registry,
    concurrency=4,           # Number of threads in ThreadPoolExecutor
    visibility_timeout=30,   # Seconds before message redelivery
    statement_timeout=25000, # PostgreSQL query timeout (ms)
)
worker.run()  # Blocks until worker.stop() is called
```

### Key Differences from Async

| Aspect | Async | Sync |
|--------|-------|------|
| Pool type | `AsyncConnectionPool` | `ConnectionPool` |
| Handler signature | `async def handle(...)` | `def handle(...)` |
| Concurrency model | asyncio tasks | `ThreadPoolExecutor` |
| I/O operations | `await conn.execute(...)` | `conn.execute(...)` |
| Pool sizing | Standard | `min_size >= concurrency` |

### Connection Pool Sizing

For sync workers, size the pool based on worker concurrency:

```python
# For concurrency=4 worker
pool = ConnectionPool(
    conninfo=DATABASE_URL,
    min_size=4,     # One connection per concurrent handler
    max_size=8,     # Headroom for spikes
    timeout=30.0,   # Fail-fast instead of waiting forever
)
```

### Sync Process Reply Router

For process management with sync workers:

```python
from commandbus.sync import SyncProcessReplyRouter

router = SyncProcessReplyRouter(
    pool=pool,
    process_repo=process_repo,
    managers={report_process.process_type: report_process},
    reply_queue="reporting__process_replies",
    domain="reporting",
)
router.run(concurrency=4)  # Blocks until router.stop() is called
```

### Performance Characteristics

The native sync implementation achieves:
- **~610 commands/sec** for fast (0ms) tasks with 6 workers
- **Near-linear scaling** for I/O-bound workloads (5 workers: ~640/s for 200ms tasks)
- **Predictable resource usage**: connections = worker_concurrency

---

## Developer Guide

This section covers how to set up command handlers and configure workers for your domain.

### 1. Define Command Handlers

Use the `@handler` decorator to mark methods as command handlers. Handlers are organized in classes with constructor-injected dependencies:

```python
from typing import Any

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

**Note:** Batch callbacks are in-memory only and will be lost on worker restart. For critical workflows, poll `get_batch()` as a fallback.

### 6. Using Reply Queues

Reply queues enable the async request-reply pattern. When a command completes, the worker sends the result to a specified queue that the caller can monitor.

**Sending a command with reply_to:**

```python
from uuid import uuid4
from commandbus import CommandBus

async def create_order_with_reply(bus: CommandBus, order_data: dict) -> UUID:
    command_id = uuid4()

    await bus.send(
        domain="orders",
        command_type="CreateOrder",
        command_id=command_id,
        data=order_data,
        reply_to="orders__replies",  # Results sent here
        correlation_id=uuid4(),      # Optional: for tracking related commands
    )

    return command_id
```

**Returning result data from handlers:**

The dict returned by your handler is included in the reply message:

```python
@handler(domain="orders", command_type="CreateOrder")
async def handle_create_order(self, cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
    order = await self._create_order(cmd.data)

    # This result dict is sent to the reply queue
    return {
        "status": "created",
        "order_id": str(order.id),
        "total": str(order.total),
        "custom_data": {"any": "data you want to return"},
    }
```

**Reply message structure:**

When `reply_to` is configured, the worker sends this message to the reply queue:

```json
{
  "command_id": "550e8400-e29b-41d4-a716-446655440000",
  "correlation_id": "660e8400-e29b-41d4-a716-446655440001",
  "outcome": "SUCCESS",
  "result": {
    "status": "created",
    "order_id": "ord_12345",
    "total": "99.99",
    "custom_data": {"any": "data you want to return"}
  }
}
```

| Field | Description |
|-------|-------------|
| `command_id` | The unique ID of the processed command |
| `correlation_id` | The correlation ID (if provided when sending) |
| `outcome` | `SUCCESS`, `FAILED`, or `CANCELED` |
| `result` | The dict returned by the handler (on success) |

**Reading replies from the queue:**

Use the PGMQ client to read replies:

```python
from commandbus.pgmq.client import PgmqClient

async def process_replies(pool: AsyncConnectionPool) -> None:
    pgmq = PgmqClient(pool)

    # Read up to 10 replies with 30s visibility timeout
    messages = await pgmq.read("orders__replies", visibility_timeout=30, batch_size=10)

    for msg in messages:
        command_id = msg.message["command_id"]
        outcome = msg.message["outcome"]
        result = msg.message.get("result")

        if outcome == "SUCCESS":
            print(f"Command {command_id} succeeded: {result}")
        else:
            print(f"Command {command_id} failed with outcome: {outcome}")

        # Delete after processing
        await pgmq.delete("orders__replies", msg.msg_id)
```

**Using batches with reply queues:**

For batch operations, set `correlation_id` to the `batch_id` to track which batch each reply belongs to:

```python
from commandbus import BatchCommand

result = await bus.create_batch(
    domain="orders",
    commands=[
        BatchCommand(
            command_type="ProcessOrder",
            command_id=uuid4(),
            data=order_data,
            correlation_id=batch_id,  # Link replies to batch
            reply_to="orders__replies",
        )
        for order_data in orders
    ],
    batch_id=batch_id,
)
```

Then aggregate replies by `correlation_id` to track batch completion.

---

## Worker Best Practices

Writing efficient and reliable handlers requires understanding how the worker processes commands.

### Concurrency Model

```
┌─────────────────────────────────────────────────────────────────────┐
│                           Worker Process                            │
│                                                                     │
│   ┌─────────────┐                                                   │
│   │  Event Loop │                                                   │
│   │   (asyncio) │                                                   │
│   └──────┬──────┘                                                   │
│          │                                                          │
│          ├──────────────┬──────────────┬──────────────┐             │
│          ▼              ▼              ▼              ▼             │
│   ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐        │
│   │  Handler  │  │  Handler  │  │  Handler  │  │  Handler  │        │
│   │  Task 1   │  │  Task 2   │  │  Task 3   │  │  Task 4   │        │
│   │           │  │           │  │           │  │           │        │
│   │  await    │  │  await    │  │  await    │  │  await    │        │
│   │  db.query │  │  api.call │  │  db.save  │  │  sleeping │        │
│   └───────────┘  └───────────┘  └───────────┘  └───────────┘        │
│                                                                     │
│   concurrency=4 means 4 handlers run concurrently                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Critical: Use Async I/O

**The #1 rule: Never block the event loop.**

```python
# ❌ BAD: Blocking call destroys concurrency
@handler(domain="orders", command_type="ProcessOrder")
async def handle_order(self, cmd: Command, ctx: HandlerContext):
    import requests
    response = requests.get("https://api.example.com")  # BLOCKS!
    # While this runs, ALL other handlers are frozen

# ✓ GOOD: Async call allows concurrency
@handler(domain="orders", command_type="ProcessOrder")
async def handle_order(self, cmd: Command, ctx: HandlerContext):
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.example.com")  # Yields!
        # Other handlers continue while waiting for response
```

### Impact of Blocking Code

```
concurrency=4, but with blocking I/O:

Time ─────────────────────────────────────────────────▶

Handler 1: ████████████████████████  (blocking HTTP call)
Handler 2:                         ▓▓▓▓▓▓▓▓  (waiting)
Handler 3:                                   ░░░░░░░░  (waiting)
Handler 4:                                             (waiting)

Effective throughput: 1 command at a time!


concurrency=4, with async I/O:

Time ─────────────────────────────────────────────────▶

Handler 1: ██░░░░██░░░░██  (I/O waits yield to others)
Handler 2: ░░██░░░░██░░░░██
Handler 3: ░░░░██░░░░██░░░░██
Handler 4: ██░░░░██░░░░██░░░░

Effective throughput: 4 commands concurrently!
```

### Handler Transaction Management

Handlers run **outside** the worker's transaction to allow long-running operations without holding database connections. Command completion happens in a separate transaction after the handler returns.

**Handlers should manage their own transactions** when they need atomicity:

```python
@handler(domain="orders", command_type="CreateOrder")
async def handle_create_order(self, cmd: Command, ctx: HandlerContext):
    # Handler manages its own transaction
    async with self._pool.connection() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO orders (id, data) VALUES (%s, %s)",
                (cmd.command_id, Json(cmd.data))
            )
            await conn.execute(
                "UPDATE inventory SET qty = qty - %s WHERE product_id = %s",
                (cmd.data["quantity"], cmd.data["product_id"])
            )
    # Transaction committed, then command marked complete

    return {"status": "created"}
```

**Handler execution flow:**

```
┌─────────────────────────────────────────────────────────────────────┐
│  1. Handler executes (manages own transactions)                     │
│     ├── async with pool.connection()                                │
│     ├── INSERT INTO orders ...                                      │
│     └── COMMIT (handler's transaction)                              │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  2. Worker completes command (separate transaction)                 │
│     ├── DELETE from PGMQ queue                                      │
│     ├── UPDATE command status to COMPLETED                          │
│     └── COMMIT                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**Why this design?**

- Handlers can perform long operations (external APIs, sleeps) without holding DB connections
- No lock contention from handlers with variable execution times
- Clear separation between business logic and command bus infrastructure

### Service Layer Pattern

Services should manage their own transactions:

```python
class PaymentService:
    def __init__(self, pool: AsyncConnectionPool):
        self._pool = pool

    async def transfer(
        self,
        from_account: str,
        to_account: str,
        amount: Decimal,
    ) -> dict:
        """Transfer money with transactional guarantee."""
        async with self._pool.connection() as conn:
            async with conn.transaction():
                return await self._transfer_impl(from_account, to_account, amount, conn)


class PaymentHandlers:
    def __init__(self, payment_service: PaymentService):
        self._service = payment_service

    @handler(domain="payments", command_type="Transfer")
    async def handle_transfer(self, cmd: Command, ctx: HandlerContext) -> dict:
        return await self._service.transfer(
            from_account=cmd.data["from"],
            to_account=cmd.data["to"],
            amount=Decimal(cmd.data["amount"]),
        )
```

### Idempotency

Commands may be delivered more than once (at-least-once delivery). Design handlers to be idempotent:

```python
@handler(domain="payments", command_type="ProcessPayment")
async def handle_payment(self, cmd: Command, ctx: HandlerContext):
    async with self._pool.connection() as conn:
        # Check if already processed
        result = await conn.execute(
            "SELECT 1 FROM payments WHERE command_id = %s",
            (cmd.command_id,)
        )
        if await result.fetchone():
            # Already processed - return cached result
            return {"status": "already_processed"}

        # Process payment
        await conn.execute(
            "INSERT INTO payments (command_id, amount) VALUES (%s, %s)",
            (cmd.command_id, cmd.data["amount"])
        )

    return {"status": "processed"}
```

### Long-Running Operations

For operations that may exceed visibility timeout, you have two options:

**Option 1: Extend visibility timeout periodically**

```python
@handler(domain="reports", command_type="GenerateReport")
async def handle_report(self, cmd: Command, ctx: HandlerContext):
    records = cmd.data["records"]
    results = []

    for i, record in enumerate(records):
        # Extend visibility every 100 records to prevent timeout
        if i > 0 and i % 100 == 0:
            await ctx.extend_visibility(30)  # Add 30 more seconds

        results.append(await process_record(record))

    return {"status": "completed", "processed": len(results)}
```

**Option 2: Break into a tracked batch of smaller commands**

```python
@handler(domain="reports", command_type="GenerateReport")
async def handle_report(self, cmd: Command, ctx: HandlerContext):
    from uuid import uuid4
    from commandbus import BatchCommand

    chunks = split_into_chunks(cmd.data["records"], chunk_size=100)
    report_id = cmd.data["report_id"]

    # Create a batch to track all chunk processing
    result = await self._bus.create_batch(
        domain="reports",
        commands=[
            BatchCommand(
                command_type="ProcessReportChunk",
                command_id=uuid4(),
                data={"chunk": chunk, "report_id": report_id, "chunk_index": i},
            )
            for i, chunk in enumerate(chunks)
        ],
        name=f"Report {report_id} chunks",
    )

    return {"status": "chunked", "batch_id": str(result.batch_id), "chunks": len(chunks)}
```

### Summary: Handler Checklist

| Requirement | Why |
|-------------|-----|
| Use `async`/`await` for all I/O | Blocking calls kill concurrency |
| Use async database drivers | psycopg3 with `AsyncConnection` |
| Use async HTTP clients | httpx, aiohttp (not requests) |
| Handle idempotency | Commands may be delivered multiple times |
| Keep handlers fast | Long operations risk visibility timeout |
| Use transactions | Ensure atomicity of database operations |
| Raise appropriate errors | `TransientCommandError` vs `PermanentCommandError` |

---

## Process Manager

The Process Manager feature orchestrates long-running, multi-step workflows by sending commands with a shared `process_id` (stored as `correlation_id`) and consuming replies from a dedicated queue. Each process tracks typed state, enforces step ordering, persists audit history, and pauses automatically if any command moves into the Troubleshooting Queue.

### Building a Custom Process

1. **Model your steps and state** – use `StrEnum` to describe each step and create a dataclass for your persisted state. The Statement Report example in `tests/e2e/app/process/statement_report.py` tracks the reporting window, account list, and intermediate file paths:

   ```python
   class StatementReportStep(StrEnum):
       QUERY = "StatementQuery"
       AGGREGATE = "StatementDataAggregation"
       RENDER = "StatementRender"

   @dataclass
   class StatementReportState:
       from_date: date
       to_date: date
       account_list: list[str]
       output_type: OutputType
       query_result_path: str | None = None
       aggregated_data_path: str | None = None
       rendered_file_path: str | None = None
   ```

2. **Subclass `BaseProcessManager`** – implement `process_type`, `domain`, `state_class`, and the lifecycle hooks:

   ```python
   class StatementReportProcess(
       BaseProcessManager[StatementReportState, StatementReportStep]
   ):
       @property
       def process_type(self) -> str:
           return "StatementReport"

       @property
       def domain(self) -> str:
           return "reporting"

       @property
       def state_class(self) -> type[StatementReportState]:
           return StatementReportState

       def get_first_step(self, state: StatementReportState) -> StatementReportStep:
           return StatementReportStep.QUERY

       async def build_command(
           self, step: StatementReportStep, state: StatementReportState
       ) -> ProcessCommand[Any]:
           match step:
               case StatementReportStep.QUERY:
                   return ProcessCommand(
                       command_type=step,
                       data=StatementQueryRequest(
                           from_date=state.from_date,
                           to_date=state.to_date,
                           account_list=state.account_list,
                       ),
                   )
               case StatementReportStep.AGGREGATE:
                   return ProcessCommand(
                       command_type=step,
                       data=StatementAggregationRequest(
                           data_path=state.query_result_path or ""
                       ),
                   )
               case StatementReportStep.RENDER:
                   return ProcessCommand(
                       command_type=step,
                       data=StatementRenderRequest(
                           aggregated_data_path=state.aggregated_data_path or "",
                           output_type=state.output_type,
                       ),
                   )
   ```

   - `update_state` consumes `Reply` objects (optionally via `ProcessResponse.from_reply`) to mutate the in-memory state before it is persisted.
   - `get_next_step` decides which step to execute next, or returns `None` when the process is finished.
   - Optional: override `get_compensation_step` for sagas that require undo steps.

3. **Wire up infrastructure**
   - Create the process metadata/audit tables by running the latest migrations.
   - Instantiate `PostgresProcessRepository` and your `BaseProcessManager` subclass with a `CommandBus`, connection pool, and reply queue name (e.g., `reporting__process_replies`). See `tests/e2e/app/main.py` for the FastAPI wiring.
   - Start the `ProcessReplyRouter` alongside your workers so replies from the process queue are routed to the correct manager:

     ```python
     router = ProcessReplyRouter(
         pool=pool,
         process_repo=process_repo,
         managers={report_process.process_type: report_process},
         reply_queue="reporting__process_replies",
         domain="reporting",
     )
     await router.run(concurrency=4)
     ```

4. **Start processes** – call `await process_manager.start(initial_payload)` to persist the initial state, send the first command, and begin tracking audit entries. Each command the manager sends automatically sets `correlation_id=process_id` and `reply_to=<process queue>`, allowing the router to deliver responses back to the manager.

The complete Statement Report flow lives in `tests/e2e/app/process/statement_report.py` and demonstrates all extension points, including typed request/response dataclasses and state updates as each report step completes.

---

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

The worker CLI automatically reads the runtime settings saved via `/settings` (async vs sync mode). After changing those settings, restart the worker process so it can reconnect using the new mode. On startup the logs print the current mode, for example `Runtime mode: sync` or `Runtime mode: async`.

In **sync mode**, workers use the native `SyncWorker` with `ThreadPoolExecutor` for thread-based concurrency and psycopg3's sync `ConnectionPool`. In **async mode**, workers use the standard asyncio-based `Worker` with `AsyncConnectionPool`. Both modes support full concurrency with predictable resource usage.

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
3. Set count (up to 1,000,000 commands)
4. Click "Generate Bulk Commands"

**Performance tip:** For maximum throughput testing, use 0ms duration with multiple workers. The native sync implementation handles 100,000+ command batches efficiently with the on-demand batch stats refresh.

### Monitoring

The E2E UI provides:
- **Dashboard**: Real-time status counts and throughput metrics
- **Commands**: List and filter commands by status
- **Troubleshooting Queue**: View and action failed commands
- **Audit Trail**: Full event history per command

---

## License

MIT
