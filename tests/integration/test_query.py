"""Integration tests for Query Commands functionality (S016)."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from psycopg_pool import AsyncConnectionPool

from commandbus.bus import CommandBus
from commandbus.models import CommandStatus


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
    """Clean up test data before and after each test."""
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM commandbus.audit")
        await conn.execute("DELETE FROM commandbus.command")
        await conn.execute("DELETE FROM pgmq.q_payments__commands")
        await conn.execute("DELETE FROM pgmq.q_reports__commands")
    yield
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM commandbus.audit")
        await conn.execute("DELETE FROM commandbus.command")
        await conn.execute("DELETE FROM pgmq.q_payments__commands")
        await conn.execute("DELETE FROM pgmq.q_reports__commands")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_commands_by_status(command_bus: CommandBus, cleanup_db: None) -> None:
    """Test querying commands by status."""
    # Send multiple commands (all start as PENDING)
    for i in range(5):
        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"account_id": str(i), "amount": 100},
        )

    # Query by status
    pending = await command_bus.query_commands(status=CommandStatus.PENDING)

    assert len(pending) == 5
    for cmd in pending:
        assert cmd.status == CommandStatus.PENDING


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_commands_by_domain(command_bus: CommandBus, cleanup_db: None) -> None:
    """Test querying commands by domain."""
    # Send commands to different domains
    for _ in range(3):
        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"amount": 100},
        )

    for _ in range(2):
        await command_bus.send(
            domain="reports",
            command_type="GenerateReport",
            command_id=uuid4(),
            data={"type": "summary"},
        )

    # Query by domain
    payments = await command_bus.query_commands(domain="payments")
    reports = await command_bus.query_commands(domain="reports")

    assert len(payments) == 3
    assert len(reports) == 2

    for cmd in payments:
        assert cmd.domain == "payments"
    for cmd in reports:
        assert cmd.domain == "reports"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_commands_by_command_type(command_bus: CommandBus, cleanup_db: None) -> None:
    """Test querying commands by command type."""
    # Send commands of different types
    for _ in range(3):
        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"amount": 100},
        )

    for _ in range(2):
        await command_bus.send(
            domain="payments",
            command_type="CreditAccount",
            command_id=uuid4(),
            data={"amount": 50},
        )

    # Query by command type
    debits = await command_bus.query_commands(domain="payments", command_type="DebitAccount")
    credits = await command_bus.query_commands(domain="payments", command_type="CreditAccount")

    assert len(debits) == 3
    assert len(credits) == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_commands_combined_filters(command_bus: CommandBus, cleanup_db: None) -> None:
    """Test querying commands with multiple filters combined."""
    # Send various commands
    for _ in range(3):
        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"amount": 100},
        )

    for _ in range(2):
        await command_bus.send(
            domain="payments",
            command_type="CreditAccount",
            command_id=uuid4(),
            data={"amount": 50},
        )

    await command_bus.send(
        domain="reports",
        command_type="DebitAccount",
        command_id=uuid4(),
        data={"amount": 25},
    )

    # Query with combined filters
    result = await command_bus.query_commands(
        status=CommandStatus.PENDING,
        domain="payments",
        command_type="DebitAccount",
    )

    assert len(result) == 3
    for cmd in result:
        assert cmd.status == CommandStatus.PENDING
        assert cmd.domain == "payments"
        assert cmd.command_type == "DebitAccount"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_commands_pagination(command_bus: CommandBus, cleanup_db: None) -> None:
    """Test querying commands with pagination."""
    # Send 10 commands
    for i in range(10):
        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"account_id": str(i), "amount": 100 + i},
        )
        # Small delay to ensure different created_at timestamps
        await asyncio.sleep(0.01)

    # Query first page
    page1 = await command_bus.query_commands(limit=3, offset=0)
    assert len(page1) == 3

    # Query second page
    page2 = await command_bus.query_commands(limit=3, offset=3)
    assert len(page2) == 3

    # Ensure pages don't overlap
    page1_ids = {cmd.command_id for cmd in page1}
    page2_ids = {cmd.command_id for cmd in page2}
    assert page1_ids.isdisjoint(page2_ids)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_commands_order_by_created_at_desc(
    command_bus: CommandBus, cleanup_db: None
) -> None:
    """Test that query results are ordered by created_at descending."""
    # Send commands with delays to ensure different timestamps
    for i in range(5):
        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"account_id": str(i)},
        )
        await asyncio.sleep(0.01)

    # Query all
    result = await command_bus.query_commands(domain="payments")

    assert len(result) == 5
    # Most recent should be first
    for i in range(len(result) - 1):
        assert result[i].created_at >= result[i + 1].created_at


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_commands_date_filter(command_bus: CommandBus, cleanup_db: None) -> None:
    """Test querying commands by date range."""
    now = datetime.now(UTC)

    # Send some commands
    for _ in range(3):
        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"amount": 100},
        )

    # Query with date filter (created_after now - 1 minute)
    created_after = now - timedelta(minutes=1)
    result = await command_bus.query_commands(created_after=created_after)

    assert len(result) == 3

    # Query with date filter far in the future
    created_after_future = now + timedelta(hours=1)
    result_future = await command_bus.query_commands(created_after=created_after_future)

    assert len(result_future) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_commands_empty_result(command_bus: CommandBus, cleanup_db: None) -> None:
    """Test query returns empty list when no matches."""
    result = await command_bus.query_commands(domain="nonexistent")

    assert result == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_command_returns_metadata(command_bus: CommandBus, cleanup_db: None) -> None:
    """Test that get_command returns full command metadata."""
    command_id = uuid4()

    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123", "amount": 100},
    )

    # Get the command
    result = await command_bus.get_command("payments", command_id)

    assert result is not None
    assert result.command_id == command_id
    assert result.domain == "payments"
    assert result.command_type == "DebitAccount"
    assert result.status == CommandStatus.PENDING


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_command_returns_none_for_unknown(
    command_bus: CommandBus, cleanup_db: None
) -> None:
    """Test that get_command returns None for unknown command."""
    result = await command_bus.get_command("payments", uuid4())

    assert result is None
