"""Integration tests for idempotent command sending (S002)."""

import os
from uuid import uuid4

import pytest
from psycopg_pool import AsyncConnectionPool

from commandbus.bus import CommandBus
from commandbus.exceptions import DuplicateCommandError
from commandbus.models import CommandStatus


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
async def cleanup_db(pool: AsyncConnectionPool):
    """Clean up test data after each test."""
    yield
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM command_bus_audit")
        await conn.execute("DELETE FROM command_bus_command")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_duplicate_command_rejected(command_bus: CommandBus, cleanup_db: None) -> None:
    """Test that sending duplicate command_id in same domain is rejected."""
    command_id = uuid4()

    # First send should succeed
    result = await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123", "amount": 100},
    )
    assert result.command_id == command_id
    assert result.msg_id > 0

    # Second send with same command_id should raise DuplicateCommandError
    with pytest.raises(DuplicateCommandError) as exc_info:
        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123", "amount": 100},
        )

    assert exc_info.value.domain == "payments"
    assert str(command_id) in exc_info.value.command_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_same_id_different_domain_allowed(command_bus: CommandBus, cleanup_db: None) -> None:
    """Test that same command_id is allowed in different domains."""
    command_id = uuid4()

    # Send to payments domain
    result1 = await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123", "amount": 100},
    )

    # Send same command_id to reports domain - should succeed
    result2 = await command_bus.send(
        domain="reports",
        command_type="GenerateReport",
        command_id=command_id,
        data={"report_type": "summary"},
    )

    assert result1.command_id == command_id
    assert result2.command_id == command_id
    # Different msg_ids from PGMQ
    assert result1.msg_id != result2.msg_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_duplicate_error_contains_command_id(
    command_bus: CommandBus, cleanup_db: None
) -> None:
    """Test that DuplicateCommandError includes the command_id for debugging."""
    command_id = uuid4()

    # First send
    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123"},
    )

    # Duplicate send
    with pytest.raises(DuplicateCommandError) as exc_info:
        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123"},
        )

    error = exc_info.value
    assert error.command_id == str(command_id)
    assert error.domain == "payments"
    assert str(command_id) in str(error)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_duplicate_metadata_created(
    command_bus: CommandBus, pool: AsyncConnectionPool, cleanup_db: None
) -> None:
    """Test that duplicate send does not create extra metadata rows."""
    command_id = uuid4()

    # First send
    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123"},
    )

    # Count rows
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT COUNT(*) FROM command_bus_command WHERE command_id = %s",
            (command_id,),
        )
        row = await cur.fetchone()
        count_before = row[0] if row else 0

    # Try duplicate send
    with pytest.raises(DuplicateCommandError):
        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123"},
        )

    # Count rows again - should be unchanged
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT COUNT(*) FROM command_bus_command WHERE command_id = %s",
            (command_id,),
        )
        row = await cur.fetchone()
        count_after = row[0] if row else 0

    assert count_after == count_before == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_client_can_query_existing_command(command_bus: CommandBus, cleanup_db: None) -> None:
    """Test that after duplicate error, client can query existing command status."""
    command_id = uuid4()

    # First send
    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123"},
    )

    # Try duplicate - get error
    with pytest.raises(DuplicateCommandError):
        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123"},
        )

    # Client can query the existing command
    metadata = await command_bus.get_command("payments", command_id)
    assert metadata is not None
    assert metadata.status == CommandStatus.PENDING
    assert metadata.command_type == "DebitAccount"
