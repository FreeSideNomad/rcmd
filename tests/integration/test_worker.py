"""Integration tests for Worker receive functionality (S004)."""

import asyncio
import os
from uuid import uuid4

import pytest
from psycopg_pool import AsyncConnectionPool

from commandbus.bus import CommandBus
from commandbus.models import CommandStatus
from commandbus.worker import Worker


@pytest.fixture
def database_url() -> str:
    """Get database URL from environment."""
    return os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/commandbus"
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
        await conn.execute("DELETE FROM command_bus_audit")
        await conn.execute("DELETE FROM command_bus_command")
        # Clean up PGMQ queues
        await conn.execute("DELETE FROM pgmq.q_payments__commands")
    yield
    # Cleanup after test
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM command_bus_audit")
        await conn.execute("DELETE FROM command_bus_command")
        await conn.execute("DELETE FROM pgmq.q_payments__commands")


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
            "SELECT attempts FROM command_bus_command WHERE command_id = %s",
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
            FROM command_bus_audit
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
            "SELECT status FROM command_bus_command WHERE command_id = %s",
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
            "UPDATE command_bus_command SET status = %s WHERE command_id = %s",
            (CommandStatus.COMPLETED.value, command_id),
        )

    # Try to receive - should skip
    received = await worker.receive()
    assert len(received) == 0
