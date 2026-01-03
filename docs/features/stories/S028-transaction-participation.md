# S028: Handler Participates in Worker Transaction

## Parent Feature

[F007 - Handler Dependency Injection](../F007-handler-dependency-injection.md)

## User Story

**As a** application developer
**I want** my handler to optionally participate in the worker's transaction
**So that** my business logic and command completion are atomic

## Context

Currently, handlers execute outside any transaction. The worker only opens a transaction for `complete()` or `fail_permanent()`. This means handler database operations are in a separate transaction from command completion.

This story adds `HandlerContext.conn` which provides the worker's database connection. When handlers use this connection, their operations are atomic with command completion.

## Acceptance Criteria (Given-When-Then)

### Scenario: Handler receives connection in context

**Given** a worker processing a command
**When** the handler is invoked
**Then** `context.conn` contains an active database connection
**And** the connection is within an open transaction

### Scenario: Handler uses connection for atomicity

**Given** a handler that performs database updates
**When** the handler uses `ctx.conn` for its operations
**And** the command completes successfully
**Then** handler updates and command completion are in same transaction
**And** both commit together

### Scenario: Handler failure rolls back transaction

**Given** a handler that performs database updates using `ctx.conn`
**When** the handler raises an exception after updates
**Then** all handler updates are rolled back
**And** command status is not changed to COMPLETED
**And** the command will be retried (visibility timeout)

### Scenario: Handler ignores connection (backwards compatible)

**Given** a handler that doesn't use `ctx.conn`
**When** the handler uses its own connection pool
**Then** handler operations are in a separate transaction
**And** this works as before (no breaking change)

### Scenario: Connection is None when not in transaction mode

**Given** a worker configured without transaction wrapping (future option)
**When** the handler accesses `ctx.conn`
**Then** `ctx.conn` is `None`
**And** the handler must handle this case

## Technical Design

### Modified HandlerContext

```python
@dataclass
class HandlerContext:
    command: Command
    attempt: int
    max_attempts: int
    msg_id: int
    visibility_extender: VisibilityExtender | None = None
    conn: AsyncConnection | None = None  # NEW
```

### Modified Worker._process_command()

```python
async def _process_command(
    self,
    received: ReceivedCommand,
    semaphore: asyncio.Semaphore,
) -> None:
    """Process a single command with transaction wrapping."""
    assert self._registry is not None

    async with semaphore:
        try:
            async with self._pool.connection() as conn, conn.transaction():
                # Inject connection into context for handler use
                context = HandlerContext(
                    command=received.command,
                    attempt=received.context.attempt,
                    max_attempts=received.context.max_attempts,
                    msg_id=received.msg_id,
                    visibility_extender=received.context.visibility_extender,
                    conn=conn,
                )

                # Handler executes within transaction
                result = await self._registry.dispatch(received.command, context)

                # Complete within same transaction
                await self._complete_in_txn(received, result, conn)

        except TransientCommandError as e:
            # Transaction rolled back, handle outside
            await self.fail(received, e, is_transient=True)
        except PermanentCommandError as e:
            # Transaction rolled back, handle outside
            await self.fail_permanent(received, e)
        except Exception as e:
            # Transaction rolled back, treat as transient
            logger.exception(f"Error processing command {received.command.command_id}")
            await self.fail(received, e, is_transient=True)
```

### Handler Using Connection

```python
class PaymentHandlers:
    def __init__(self, payment_service: PaymentService):
        self._service = payment_service

    @handler(domain="payments", command_type="Transfer")
    async def handle_transfer(self, cmd: Command, ctx: HandlerContext) -> dict:
        # Both operations use same connection = same transaction
        await self._service.debit(
            cmd.data["from_account"],
            cmd.data["amount"],
            conn=ctx.conn,
        )
        await self._service.credit(
            cmd.data["to_account"],
            cmd.data["amount"],
            conn=ctx.conn,
        )
        return {"status": "transferred"}
        # If we return successfully, complete() commits the transaction
        # If we raise, transaction rolls back, command retries
```

### Service Layer Pattern

```python
class PaymentService:
    async def debit(
        self,
        account_id: str,
        amount: Decimal,
        conn: AsyncConnection | None = None,
    ) -> dict:
        """Debit account. Uses provided conn or acquires from pool."""
        if conn is not None:
            return await self._debit_impl(account_id, amount, conn)

        async with self._pool.connection() as acquired_conn:
            return await self._debit_impl(account_id, amount, acquired_conn)
```

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Context has connection | Integration | `tests/integration/test_transaction.py::test_context_has_connection` |
| Atomic with completion | Integration | `tests/integration/test_transaction.py::test_handler_atomic_with_completion` |
| Rollback on failure | Integration | `tests/integration/test_transaction.py::test_handler_rollback_on_failure` |
| Backwards compatible | Integration | `tests/integration/test_transaction.py::test_handler_without_conn` |
| Conn is optional | Unit | `tests/unit/test_models.py::test_handler_context_conn_optional` |

## Example Test

```python
import pytest
from uuid import uuid4
from psycopg_pool import AsyncConnectionPool

from commandbus import CommandBus, Worker, HandlerRegistry, Command, HandlerContext
from commandbus.handler import handler


class TestTransactionParticipation:
    @pytest.fixture
    async def pool(self, database_url):
        pool = AsyncConnectionPool(conninfo=database_url)
        await pool.open()
        yield pool
        await pool.close()

    @pytest.mark.asyncio
    async def test_handler_receives_connection(self, pool):
        """Test that handler receives connection in context."""
        received_conn = None

        class TestHandlers:
            @handler(domain="test", command_type="CheckConn")
            async def handle(self, cmd: Command, ctx: HandlerContext) -> dict:
                nonlocal received_conn
                received_conn = ctx.conn
                return {"has_conn": ctx.conn is not None}

        registry = HandlerRegistry()
        registry.register_instance(TestHandlers())

        bus = CommandBus(pool)
        worker = Worker(pool, domain="test", registry=registry)

        command_id = uuid4()
        await bus.send(domain="test", command_type="CheckConn", command_id=command_id, data={})

        commands = await worker.receive(batch_size=1)
        assert len(commands) == 1

        # Process with transaction wrapping
        await worker._process_command(commands[0], asyncio.Semaphore(1))

        assert received_conn is not None

    @pytest.mark.asyncio
    async def test_handler_operations_atomic_with_completion(self, pool):
        """Test that handler DB operations commit with command completion."""
        class TestHandlers:
            @handler(domain="test", command_type="AtomicTest")
            async def handle(self, cmd: Command, ctx: HandlerContext) -> dict:
                # Insert using handler's connection
                async with ctx.conn.cursor() as cur:
                    await cur.execute(
                        "INSERT INTO test_data (id, value) VALUES (%s, %s)",
                        (cmd.data["id"], cmd.data["value"]),
                    )
                return {"inserted": True}

        registry = HandlerRegistry()
        registry.register_instance(TestHandlers())

        bus = CommandBus(pool)
        worker = Worker(pool, domain="test", registry=registry)

        command_id = uuid4()
        test_id = uuid4()
        await bus.send(
            domain="test",
            command_type="AtomicTest",
            command_id=command_id,
            data={"id": str(test_id), "value": "test"},
        )

        commands = await worker.receive(batch_size=1)
        await worker._process_command(commands[0], asyncio.Semaphore(1))

        # Verify both insert and completion committed
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT value FROM test_data WHERE id = %s", (str(test_id),))
                row = await cur.fetchone()
                assert row[0] == "test"

        metadata = await bus.get_command("test", command_id)
        assert metadata.status == CommandStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_handler_failure_rolls_back(self, pool):
        """Test that handler failure rolls back all operations."""
        class TestHandlers:
            @handler(domain="test", command_type="FailTest")
            async def handle(self, cmd: Command, ctx: HandlerContext) -> dict:
                # Insert using handler's connection
                async with ctx.conn.cursor() as cur:
                    await cur.execute(
                        "INSERT INTO test_data (id, value) VALUES (%s, %s)",
                        (cmd.data["id"], "should_rollback"),
                    )
                # Then fail
                raise TransientCommandError("FAIL", "Intentional failure")

        registry = HandlerRegistry()
        registry.register_instance(TestHandlers())

        bus = CommandBus(pool)
        worker = Worker(pool, domain="test", registry=registry)

        command_id = uuid4()
        test_id = uuid4()
        await bus.send(
            domain="test",
            command_type="FailTest",
            command_id=command_id,
            data={"id": str(test_id)},
        )

        commands = await worker.receive(batch_size=1)
        await worker._process_command(commands[0], asyncio.Semaphore(1))

        # Verify insert was rolled back
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT value FROM test_data WHERE id = %s", (str(test_id),))
                row = await cur.fetchone()
                assert row is None  # Rolled back

        # Command should not be completed
        metadata = await bus.get_command("test", command_id)
        assert metadata.status != CommandStatus.COMPLETED
```

## Story Size

L (4000-8000 tokens, large feature)

## Priority (MoSCoW)

Must Have

## Dependencies

- [S026](S026-handler-decorator-class.md) - @handler decorator
- [S027](S027-register-instance.md) - register_instance() for testing

## Technical Notes

- Worker opens transaction before calling handler
- Connection passed via `HandlerContext.conn`
- Transaction commits only if handler returns successfully
- Any exception causes transaction rollback
- `fail()` and `fail_permanent()` run outside the transaction (new connections)
- Visibility timeout prevents double-processing during retry

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Long transactions | Lock contention | Document VT extension for long handlers |
| Connection leak | Resource exhaustion | Context manager ensures cleanup |
| Deadlock | Processing stalls | Consistent lock ordering in handlers |

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/models.py` - Add conn to HandlerContext
- `src/commandbus/worker.py` - Modify _process_command()

**Constraints:**
- Must be backwards compatible (conn is optional)
- Transaction must wrap handler + complete/audit
- Exceptions must roll back cleanly

**Verification Steps:**
1. Run `pytest tests/integration/test_transaction.py -v`
2. Run `make test-integration`
3. Verify existing tests still pass

## Definition of Done

- [ ] Code complete and reviewed
- [ ] HandlerContext.conn added
- [ ] Worker wraps handler in transaction
- [ ] Integration tests written and passing
- [ ] Existing handler tests still pass
- [ ] Documentation updated
