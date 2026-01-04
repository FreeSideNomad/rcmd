"""Integration tests for Audit Trail functionality (S015)."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from psycopg_pool import AsyncConnectionPool

from commandbus.bus import CommandBus
from commandbus.exceptions import PermanentCommandError, TransientCommandError
from commandbus.handler import HandlerRegistry
from commandbus.models import AuditEvent, HandlerContext
from commandbus.ops.troubleshooting import TroubleshootingQueue
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
async def tsq(pool: AsyncConnectionPool) -> TroubleshootingQueue:
    """Create a TroubleshootingQueue with real database connection."""
    return TroubleshootingQueue(pool)


@pytest.fixture
async def cleanup_db(pool: AsyncConnectionPool):
    """Clean up test data before and after each test."""
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM commandbus.audit")
        await conn.execute("DELETE FROM commandbus.command")
        await conn.execute("DELETE FROM pgmq.q_payments__commands")
        await conn.execute("DELETE FROM pgmq.q_reports__replies")
    yield
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM commandbus.audit")
        await conn.execute("DELETE FROM commandbus.command")
        await conn.execute("DELETE FROM pgmq.q_payments__commands")
        await conn.execute("DELETE FROM pgmq.q_reports__replies")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_audit_trail_after_send(command_bus: CommandBus, cleanup_db: None) -> None:
    """Test that SENT event is recorded in audit trail."""
    command_id = uuid4()

    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"account_id": "123", "amount": 100},
    )

    events = await command_bus.get_audit_trail(command_id)

    assert len(events) == 1
    assert isinstance(events[0], AuditEvent)
    assert events[0].event_type == "SENT"
    assert events[0].domain == "payments"
    assert events[0].command_id == command_id
    assert events[0].details is not None
    assert events[0].details["command_type"] == "DebitAccount"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_audit_trail_with_domain_filter(
    command_bus: CommandBus, cleanup_db: None
) -> None:
    """Test audit trail with domain filter."""
    command_id = uuid4()

    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"amount": 100},
    )

    # With matching domain
    events = await command_bus.get_audit_trail(command_id, domain="payments")
    assert len(events) == 1

    # With non-matching domain
    events_other = await command_bus.get_audit_trail(command_id, domain="reports")
    assert len(events_other) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_audit_trail_unknown_command(command_bus: CommandBus, cleanup_db: None) -> None:
    """Test that unknown command returns empty list."""
    unknown_id = uuid4()

    events = await command_bus.get_audit_trail(unknown_id)

    assert events == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_audit_trail_chronological_order(
    command_bus: CommandBus, worker: Worker, cleanup_db: None
) -> None:
    """Test that events are returned in chronological order."""
    command_id = uuid4()

    # Send command
    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"amount": 100},
    )

    # Receive and complete
    registry = HandlerRegistry()

    @registry.handler("payments", "DebitAccount")
    async def handle(cmd, ctx: HandlerContext) -> dict:
        return {"status": "ok"}

    received = await worker.receive(batch_size=1)
    assert len(received) == 1
    await worker.complete(received[0], result={"status": "ok"})

    # Get audit trail
    events = await command_bus.get_audit_trail(command_id)

    assert len(events) >= 2
    # Events should be in order: SENT first, then RECEIVED/COMPLETED
    assert events[0].event_type == "SENT"
    # Verify timestamps are in ascending order
    for i in range(1, len(events)):
        assert events[i].timestamp >= events[i - 1].timestamp


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_trail_includes_failure_details(
    command_bus: CommandBus, worker: Worker, cleanup_db: None
) -> None:
    """Test that failure event includes error details."""
    command_id = uuid4()

    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"amount": 100},
    )

    received = await worker.receive(batch_size=1)
    assert len(received) == 1

    error = TransientCommandError(code="TIMEOUT", message="Database timeout")
    await worker.fail(received[0], error)

    events = await command_bus.get_audit_trail(command_id)

    # Find the FAILED event
    failed_events = [e for e in events if e.event_type == "FAILED"]
    assert len(failed_events) >= 1

    failed_event = failed_events[0]
    assert failed_event.details is not None
    assert failed_event.details.get("error_type") == "TRANSIENT"
    assert failed_event.details.get("error_code") == "TIMEOUT"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_trail_full_lifecycle(
    command_bus: CommandBus,
    worker: Worker,
    tsq: TroubleshootingQueue,
    pool: AsyncConnectionPool,
    cleanup_db: None,
) -> None:
    """Test full lifecycle audit: SENT, RECEIVED, FAILED, MOVED_TO_TSQ, OPERATOR_COMPLETE."""
    command_id = uuid4()

    # 1. Send command
    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"amount": 100},
        max_attempts=1,  # Will move to TSQ after first failure
    )

    # 2. Receive and fail with permanent error
    received = await worker.receive(batch_size=1)
    assert len(received) == 1

    error = PermanentCommandError(code="INVALID_ACCOUNT", message="Account not found")
    await worker.fail_permanent(received[0], error)

    # 3. Complete via operator
    await tsq.operator_complete(
        domain="payments",
        command_id=command_id,
        operator="admin@example.com",
        result_data={"manually_resolved": True},
    )

    # 4. Get full audit trail
    events = await command_bus.get_audit_trail(command_id)

    event_types = [e.event_type for e in events]

    # Verify all lifecycle events are present
    # Note: fail_permanent goes directly from RECEIVED to MOVED_TO_TSQ (no FAILED event)
    assert "SENT" in event_types
    assert "RECEIVED" in event_types
    assert "MOVED_TO_TSQ" in event_types
    assert "OPERATOR_COMPLETE" in event_types

    # Verify operator identity is in OPERATOR_COMPLETE event
    operator_event = next(e for e in events if e.event_type == "OPERATOR_COMPLETE")
    assert operator_event.details is not None
    assert operator_event.details.get("operator") == "admin@example.com"
