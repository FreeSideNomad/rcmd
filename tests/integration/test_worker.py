"""Integration tests for Worker receive functionality (S004)."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from psycopg_pool import AsyncConnectionPool

from commandbus.bus import CommandBus
from commandbus.handler import HandlerRegistry
from commandbus.models import Command as Cmd
from commandbus.models import CommandStatus, HandlerContext
from commandbus.worker import Worker


@pytest.fixture
def database_url() -> str:
    """Get database URL from environment."""
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/commandbus",  # pragma: allowlist secret
    )


@pytest.fixture
async def pool(database_url: str) -> AsyncConnectionPool:
    """Create a connection pool for testing."""
    async with AsyncConnectionPool(
        conninfo=database_url, min_size=1, max_size=5, open=False
    ) as pool:
        yield pool


@pytest.fixture
async def command_bus(pool: AsyncConnectionPool) -> CommandBus:
    """Create a CommandBus with real database connection."""
    return CommandBus(pool)


@pytest.fixture
async def worker(pool: AsyncConnectionPool) -> Worker:
    """Create a Worker with real database connection."""
    return Worker(pool, domain="payments", visibility_timeout=5)


@pytest.fixture
async def cleanup_db(pool: AsyncConnectionPool):
    """Clean up test data before and after each test."""
    # Cleanup before test
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM commandbus.audit")
        await conn.execute("DELETE FROM commandbus.command")
        # Clean up PGMQ queues
        await conn.execute("DELETE FROM pgmq.q_payments__commands")
        await conn.execute("DELETE FROM pgmq.q_reports__replies")
    yield
    # Cleanup after test
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM commandbus.audit")
        await conn.execute("DELETE FROM commandbus.command")
        await conn.execute("DELETE FROM pgmq.q_payments__commands")
        await conn.execute("DELETE FROM pgmq.q_reports__replies")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_receive_returns_command(
    command_bus: CommandBus, worker: Worker, cleanup_db: None
) -> None:
    """Test that worker receives a sent command."""
    command_id = uuid4()

    # Send a command
    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123", "amount": 100},
    )

    # Receive the command
    received = await worker.receive(batch_size=1)

    assert len(received) == 1
    cmd = received[0]
    assert cmd.command.command_id == command_id
    assert cmd.command.command_type == "DebitAccount"
    assert cmd.command.data == {"account_id": "123", "amount": 100}
    assert cmd.context.attempt == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_receive_empty_queue(worker: Worker, cleanup_db: None) -> None:
    """Test receiving from an empty queue returns empty list."""
    received = await worker.receive()

    assert received == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_receive_increments_attempts(
    command_bus: CommandBus, worker: Worker, pool: AsyncConnectionPool, cleanup_db: None
) -> None:
    """Test that receiving a command increments attempts."""
    command_id = uuid4()

    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123"},
    )

    # Receive the command
    received = await worker.receive()
    assert received[0].context.attempt == 1

    # Check metadata was updated
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT attempts FROM commandbus.command WHERE command_id = %s",
            (command_id,),
        )
        row = await cur.fetchone()
        assert row is not None
        assert row[0] == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_receive_records_audit_event(
    command_bus: CommandBus, worker: Worker, pool: AsyncConnectionPool, cleanup_db: None
) -> None:
    """Test that receiving records a RECEIVED audit event."""
    command_id = uuid4()

    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123"},
    )

    await worker.receive()

    # Check audit event was recorded
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT event_type, details_json
            FROM commandbus.audit
            WHERE command_id = %s AND event_type = 'RECEIVED'
            """,
            (command_id,),
        )
        row = await cur.fetchone()
        assert row is not None
        assert row[0] == "RECEIVED"
        details = row[1]
        assert details["attempt"] == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_visibility_timeout_redelivery(
    command_bus: CommandBus, pool: AsyncConnectionPool, cleanup_db: None
) -> None:
    """Test that message reappears after visibility timeout."""
    command_id = uuid4()

    # Create worker with short visibility timeout
    worker = Worker(pool, domain="payments", visibility_timeout=2)

    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123"},
    )

    # First receive
    received1 = await worker.receive()
    assert len(received1) == 1
    assert received1[0].context.attempt == 1

    # Immediately try to receive again - should be empty (message invisible)
    received2 = await worker.receive()
    assert len(received2) == 0

    # Wait for visibility timeout to expire
    await asyncio.sleep(3)

    # Now message should reappear
    received3 = await worker.receive()
    assert len(received3) == 1
    assert received3[0].context.attempt == 2  # Attempt incremented


@pytest.mark.integration
@pytest.mark.asyncio
async def test_receive_updates_status_to_in_progress(
    command_bus: CommandBus, worker: Worker, pool: AsyncConnectionPool, cleanup_db: None
) -> None:
    """Test that receiving updates status to IN_PROGRESS."""
    command_id = uuid4()

    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123"},
    )

    await worker.receive()

    # Check status was updated
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT status FROM commandbus.command WHERE command_id = %s",
            (command_id,),
        )
        row = await cur.fetchone()
        assert row is not None
        assert row[0] == CommandStatus.IN_PROGRESS.value


@pytest.mark.integration
@pytest.mark.asyncio
async def test_receive_skips_completed_command(
    command_bus: CommandBus, worker: Worker, pool: AsyncConnectionPool, cleanup_db: None
) -> None:
    """Test that completed commands are skipped."""
    command_id = uuid4()

    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123"},
    )

    # Manually mark as completed
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE commandbus.command SET status = %s WHERE command_id = %s",
            (CommandStatus.COMPLETED.value, command_id),
        )

    # Try to receive - should skip
    received = await worker.receive()
    assert len(received) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_complete_deletes_message_and_updates_status(
    command_bus: CommandBus, worker: Worker, pool: AsyncConnectionPool, cleanup_db: None
) -> None:
    """Test that complete deletes message and updates status."""
    command_id = uuid4()

    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123"},
    )

    # Receive the command
    received = await worker.receive()
    assert len(received) == 1

    # Complete the command
    await worker.complete(received[0])

    # Verify status is COMPLETED
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT status FROM commandbus.command WHERE command_id = %s",
            (command_id,),
        )
        row = await cur.fetchone()
        assert row is not None
        assert row[0] == CommandStatus.COMPLETED.value

    # Verify message is deleted (not reappearing after visibility timeout)
    await asyncio.sleep(6)  # Wait past visibility timeout
    received_again = await worker.receive()
    assert len(received_again) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_complete_records_audit_event(
    command_bus: CommandBus, worker: Worker, pool: AsyncConnectionPool, cleanup_db: None
) -> None:
    """Test that complete records COMPLETED audit event."""
    command_id = uuid4()

    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123"},
    )

    received = await worker.receive()
    await worker.complete(received[0])

    # Verify audit event was recorded
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT event_type, details_json
            FROM commandbus.audit
            WHERE command_id = %s AND event_type = 'COMPLETED'
            """,
            (command_id,),
        )
        row = await cur.fetchone()
        assert row is not None
        assert row[0] == "COMPLETED"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_complete_with_reply_sends_to_reply_queue(
    command_bus: CommandBus, pool: AsyncConnectionPool, cleanup_db: None
) -> None:
    """Test that complete sends reply to reply queue."""
    command_id = uuid4()
    reply_queue = "reports__replies"

    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123"},
        reply_to=reply_queue,
    )

    worker = Worker(pool, domain="payments", visibility_timeout=5)
    received = await worker.receive()
    assert len(received) == 1

    # Complete with result
    await worker.complete(received[0], result={"balance": 900})

    # Read reply from reply queue
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT * FROM pgmq.read(%s, %s, %s)",
            (reply_queue, 30, 1),
        )
        rows = await cur.fetchall()
        assert len(rows) == 1
        reply_message = rows[0][4]  # message column
        assert reply_message["command_id"] == str(command_id)
        assert reply_message["outcome"] == "SUCCESS"
        assert reply_message["result"] == {"balance": 900}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_complete_is_atomic(
    command_bus: CommandBus, pool: AsyncConnectionPool, cleanup_db: None
) -> None:
    """Test that complete operations are atomic (all or nothing)."""
    command_id = uuid4()

    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123"},
    )

    worker = Worker(pool, domain="payments", visibility_timeout=5)
    received = await worker.receive()

    # Complete successfully
    await worker.complete(received[0])

    # Verify all operations happened together:
    # 1. Status is COMPLETED
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT status FROM commandbus.command WHERE command_id = %s",
            (command_id,),
        )
        row = await cur.fetchone()
        assert row[0] == CommandStatus.COMPLETED.value

        # 2. Audit event exists
        await cur.execute(
            """
            SELECT COUNT(*) FROM commandbus.audit
            WHERE command_id = %s AND event_type = 'COMPLETED'
            """,
            (command_id,),
        )
        row = await cur.fetchone()
        assert row[0] == 1

    # 3. Message is gone from queue (already verified it doesn't reappear)


@pytest.fixture
def handler_registry() -> HandlerRegistry:
    """Create a handler registry for testing."""
    return HandlerRegistry()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_run_processes_commands(
    command_bus: CommandBus,
    pool: AsyncConnectionPool,
    handler_registry: HandlerRegistry,
    cleanup_db: None,
) -> None:
    """Test that worker.run() processes commands with handlers."""
    command_id = uuid4()
    processed_commands: list[uuid4] = []

    @handler_registry.handler("payments", "DebitAccount")
    async def handle_debit(command: Cmd, context: HandlerContext) -> dict:
        processed_commands.append(command.command_id)
        return {"processed": True}

    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123", "amount": 100},
    )

    worker = Worker(pool, domain="payments", registry=handler_registry, visibility_timeout=5)

    # Run worker in background and stop after processing
    async def run_and_stop() -> None:
        await asyncio.sleep(0.5)  # Let worker process
        await worker.stop()

    await asyncio.gather(
        worker.run(concurrency=1, poll_interval=0.1, use_notify=False),
        run_and_stop(),
    )

    assert command_id in processed_commands

    # Verify command is completed
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT status FROM commandbus.command WHERE command_id = %s",
            (command_id,),
        )
        row = await cur.fetchone()
        assert row is not None
        assert row[0] == CommandStatus.COMPLETED.value


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_concurrent_processing(
    command_bus: CommandBus,
    pool: AsyncConnectionPool,
    handler_registry: HandlerRegistry,
    cleanup_db: None,
) -> None:
    """Test that worker processes multiple commands concurrently."""
    command_ids = [uuid4() for _ in range(3)]
    processing_times: dict[uuid4, float] = {}
    start_time = asyncio.get_event_loop().time()

    @handler_registry.handler("payments", "DebitAccount")
    async def handle_debit(command: Cmd, context: HandlerContext) -> dict:
        processing_times[command.command_id] = asyncio.get_event_loop().time() - start_time
        await asyncio.sleep(0.2)  # Simulate processing time
        return {"processed": True}

    # Send 3 commands
    for cmd_id in command_ids:
        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=cmd_id,
            data={"account_id": "123"},
        )

    worker = Worker(pool, domain="payments", registry=handler_registry, visibility_timeout=5)

    async def run_and_stop() -> None:
        await asyncio.sleep(1.0)  # Let worker process all
        await worker.stop()

    await asyncio.gather(
        worker.run(concurrency=3, poll_interval=0.1, use_notify=False),
        run_and_stop(),
    )

    # All commands should be processed
    assert len(processing_times) == 3

    # With concurrency=3, all commands should start processing around the same time
    times = list(processing_times.values())
    # The difference between first and last start time should be small
    assert max(times) - min(times) < 0.3  # All started within 0.3s


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_graceful_shutdown(
    command_bus: CommandBus,
    pool: AsyncConnectionPool,
    handler_registry: HandlerRegistry,
    cleanup_db: None,
) -> None:
    """Test that worker waits for in-flight commands on shutdown."""
    command_id = uuid4()
    handler_started = asyncio.Event()
    handler_completed = asyncio.Event()

    @handler_registry.handler("payments", "DebitAccount")
    async def handle_debit(command: Cmd, context: HandlerContext) -> dict:
        handler_started.set()
        await asyncio.sleep(0.3)  # Simulate processing
        handler_completed.set()
        return {"processed": True}

    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123"},
    )

    worker = Worker(pool, domain="payments", registry=handler_registry, visibility_timeout=5)

    async def stop_during_processing() -> None:
        await handler_started.wait()  # Wait until handler starts
        await worker.stop()  # Request stop while processing

    await asyncio.gather(
        worker.run(concurrency=1, poll_interval=0.1, use_notify=False),
        stop_during_processing(),
    )

    # Handler should have completed despite shutdown request
    assert handler_completed.is_set()

    # Command should be completed
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT status FROM commandbus.command WHERE command_id = %s",
            (command_id,),
        )
        row = await cur.fetchone()
        assert row is not None
        assert row[0] == CommandStatus.COMPLETED.value


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_poll_fallback(
    command_bus: CommandBus,
    pool: AsyncConnectionPool,
    handler_registry: HandlerRegistry,
    cleanup_db: None,
) -> None:
    """Test that worker polls for commands at regular intervals."""
    command_id = uuid4()
    processed_commands: list[uuid4] = []

    @handler_registry.handler("payments", "DebitAccount")
    async def handle_debit(command: Cmd, context: HandlerContext) -> dict:
        processed_commands.append(command.command_id)
        return {"processed": True}

    # Send command
    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123"},
    )

    worker = Worker(pool, domain="payments", registry=handler_registry, visibility_timeout=5)

    async def run_and_stop() -> None:
        await asyncio.sleep(0.3)  # Poll interval is 0.1, should process
        await worker.stop()

    # Use polling only (no notify)
    await asyncio.gather(
        worker.run(concurrency=1, poll_interval=0.1, use_notify=False),
        run_and_stop(),
    )

    assert command_id in processed_commands
