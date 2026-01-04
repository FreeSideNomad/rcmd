"""Integration tests for correlation ID functionality (S003)."""

import os
from uuid import uuid4

import pytest
from psycopg_pool import AsyncConnectionPool

from commandbus.bus import CommandBus


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
async def cleanup_db(pool: AsyncConnectionPool):
    """Clean up test data after each test."""
    yield
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM commandbus.audit")
        await conn.execute("DELETE FROM commandbus.command")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_send_with_explicit_correlation_id(
    command_bus: CommandBus, pool: AsyncConnectionPool, cleanup_db: None
) -> None:
    """Test that explicit correlation_id is stored in metadata."""
    command_id = uuid4()
    correlation_id = uuid4()

    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123", "amount": 100},
        correlation_id=correlation_id,
    )

    # Verify correlation_id in metadata
    metadata = await command_bus.get_command("payments", command_id)
    assert metadata is not None
    assert metadata.correlation_id == correlation_id

    # Verify correlation_id in audit event
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT details_json FROM commandbus.audit WHERE command_id = %s",
            (command_id,),
        )
        row = await cur.fetchone()
        assert row is not None
        details = row[0]
        assert details["correlation_id"] == str(correlation_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_send_generates_correlation_id_when_not_provided(
    command_bus: CommandBus, pool: AsyncConnectionPool, cleanup_db: None
) -> None:
    """Test that correlation_id is auto-generated when not provided."""
    command_id = uuid4()

    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123", "amount": 100},
        # No correlation_id provided
    )

    # Verify correlation_id was auto-generated in metadata
    metadata = await command_bus.get_command("payments", command_id)
    assert metadata is not None
    assert metadata.correlation_id is not None

    # Verify correlation_id in audit event matches metadata
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT details_json FROM commandbus.audit WHERE command_id = %s",
            (command_id,),
        )
        row = await cur.fetchone()
        assert row is not None
        details = row[0]
        assert details["correlation_id"] == str(metadata.correlation_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_correlation_id_in_queue_message(
    command_bus: CommandBus, pool: AsyncConnectionPool, cleanup_db: None
) -> None:
    """Test that correlation_id is included in the PGMQ message payload."""
    command_id = uuid4()
    correlation_id = uuid4()

    result = await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123", "amount": 100},
        correlation_id=correlation_id,
    )

    # Read the message from PGMQ queue to verify correlation_id
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT message FROM pgmq.q_payments__commands WHERE msg_id = %s",
            (result.msg_id,),
        )
        row = await cur.fetchone()
        assert row is not None
        message = row[0]
        assert message["correlation_id"] == str(correlation_id)
