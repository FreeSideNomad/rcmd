"""Integration tests for retry exhaustion flow."""

import asyncio
import contextlib
import os
from uuid import uuid4

import pytest
from psycopg_pool import AsyncConnectionPool

from commandbus import (
    Command,
    CommandBus,
    CommandStatus,
    HandlerContext,
    HandlerRegistry,
    PgmqClient,
    PostgresAuditLogger,
    PostgresCommandRepository,
    RetryPolicy,
    TransientCommandError,
    Worker,
)
from commandbus.repositories.audit import AuditEventType


@pytest.fixture
def database_url() -> str:
    """Get database URL from environment."""
    return os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/commandbus"
    )


@pytest.fixture
async def pool(database_url: str) -> AsyncConnectionPool:
    """Create a connection pool for testing."""
    async with AsyncConnectionPool(conninfo=database_url, min_size=1, max_size=5, open=False) as p:
        yield p


@pytest.fixture
async def command_bus(pool: AsyncConnectionPool) -> CommandBus:
    """Create a CommandBus with real database connection."""
    return CommandBus(pool)


@pytest.fixture
def handler_registry() -> HandlerRegistry:
    """Create handler registry."""
    return HandlerRegistry()


class TestRetryExhaustionFlow:
    """Integration tests for retry exhaustion handling flow."""

    @pytest.mark.asyncio
    async def test_exhausted_command_moves_to_tsq(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
    ) -> None:
        """Test that exhausted retries move command to troubleshooting queue."""
        command_id = uuid4()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            # Always fail with transient error
            raise TransientCommandError("TIMEOUT", "Database connection timeout")

        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123", "amount": 100},
        )

        # Create worker with max_attempts=3
        worker = Worker(
            pool,
            domain="payments",
            registry=handler_registry,
            retry_policy=RetryPolicy(max_attempts=3, backoff_schedule=[1, 1, 1]),
        )

        # Receive and fail attempt 1
        received = await worker.receive()
        assert len(received) == 1
        assert received[0].context.attempt == 1
        await worker.fail(received[0], TransientCommandError("TIMEOUT", "Timeout"))

        # Wait and receive attempt 2
        await asyncio.sleep(1.5)
        received = await worker.receive()
        assert len(received) == 1
        assert received[0].context.attempt == 2
        await worker.fail(received[0], TransientCommandError("TIMEOUT", "Timeout"))

        # Wait and receive attempt 3 (final)
        await asyncio.sleep(1.5)
        received = await worker.receive()
        assert len(received) == 1
        assert received[0].context.attempt == 3

        # This should trigger exhaustion and move to TSQ
        await worker.fail(received[0], TransientCommandError("TIMEOUT", "Timeout"))

        # Check status is IN_TROUBLESHOOTING_QUEUE
        command_repo = PostgresCommandRepository(pool)
        metadata = await command_repo.get("payments", command_id)
        assert metadata is not None
        assert metadata.status == CommandStatus.IN_TROUBLESHOOTING_QUEUE

    @pytest.mark.asyncio
    async def test_exhausted_command_records_exhausted_audit_event(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
    ) -> None:
        """Test that exhausted command records MOVED_TO_TSQ with EXHAUSTED reason."""
        command_id = uuid4()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            raise TransientCommandError("RATE_LIMIT", "Too many requests")

        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123"},
        )

        # Worker with max_attempts=1 (immediate exhaustion)
        worker = Worker(
            pool,
            domain="payments",
            registry=handler_registry,
            retry_policy=RetryPolicy(max_attempts=1, backoff_schedule=[1]),
        )

        received = await worker.receive()
        assert received[0].context.attempt == 1

        # First attempt is also max attempts - should exhaust
        await worker.fail(received[0], TransientCommandError("RATE_LIMIT", "Too many requests"))

        # Check audit trail
        audit_logger = PostgresAuditLogger(pool)
        events = await audit_logger.get_events(command_id, domain="payments")

        # Should have MOVED_TO_TSQ event
        event_types = [e["event_type"] for e in events]
        assert AuditEventType.MOVED_TO_TSQ.value in event_types

        # Check MOVED_TO_TSQ event has EXHAUSTED reason
        tsq_event = next(e for e in events if e["event_type"] == AuditEventType.MOVED_TO_TSQ.value)
        assert tsq_event["details"]["reason"] == "EXHAUSTED"
        assert tsq_event["details"]["error_type"] == "TRANSIENT"
        assert tsq_event["details"]["error_code"] == "RATE_LIMIT"

    @pytest.mark.asyncio
    async def test_exhausted_command_no_further_retries(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
    ) -> None:
        """Test that exhausted commands do not get further retries."""
        command_id = uuid4()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            raise TransientCommandError("TIMEOUT", "Timeout")

        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123"},
        )

        # Worker with max_attempts=1
        worker = Worker(
            pool,
            domain="payments",
            registry=handler_registry,
            visibility_timeout=1,
            retry_policy=RetryPolicy(max_attempts=1, backoff_schedule=[1]),
        )

        # Receive and exhaust
        received = await worker.receive()
        await worker.fail(received[0], TransientCommandError("TIMEOUT", "Timeout"))

        # Wait and try to receive - should get nothing
        await asyncio.sleep(2)
        more_messages = await worker.receive()
        assert len(more_messages) == 0

    @pytest.mark.asyncio
    async def test_custom_max_attempts_exhaustion(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
    ) -> None:
        """Test exhaustion with custom max_attempts (5 attempts)."""
        command_id = uuid4()
        attempts_seen: list[int] = []

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            attempts_seen.append(context.attempt)
            raise TransientCommandError("TIMEOUT", "Timeout")

        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123"},
        )

        # Worker with max_attempts=5
        worker = Worker(
            pool,
            domain="payments",
            registry=handler_registry,
            visibility_timeout=1,
            retry_policy=RetryPolicy(max_attempts=5, backoff_schedule=[1, 1, 1, 1]),
        )

        # Process through all 5 attempts
        for expected_attempt in range(1, 6):
            received = await worker.receive()
            if not received:
                await asyncio.sleep(1.5)
                received = await worker.receive()
            assert len(received) == 1
            assert received[0].context.attempt == expected_attempt
            await worker.fail(received[0], TransientCommandError("TIMEOUT", "Timeout"))
            if expected_attempt < 5:
                await asyncio.sleep(1.5)

        # After 5 attempts, should be in TSQ
        command_repo = PostgresCommandRepository(pool)
        metadata = await command_repo.get("payments", command_id)
        assert metadata is not None
        assert metadata.status == CommandStatus.IN_TROUBLESHOOTING_QUEUE
        assert metadata.attempts == 5

    @pytest.mark.asyncio
    async def test_worker_run_handles_exhaustion(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
    ) -> None:
        """Test that worker.run() properly handles retry exhaustion."""
        command_id = uuid4()
        attempts_seen: list[int] = []
        exhausted = asyncio.Event()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            attempts_seen.append(context.attempt)
            if context.attempt >= 2:
                exhausted.set()  # Signal after max attempts reached
            raise TransientCommandError("TIMEOUT", "Always fails")

        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123"},
        )

        # Worker with max_attempts=2
        worker = Worker(
            pool,
            domain="payments",
            registry=handler_registry,
            visibility_timeout=1,
            retry_policy=RetryPolicy(max_attempts=2, backoff_schedule=[1]),
        )

        async def run_worker() -> None:
            await worker.run(concurrency=1, poll_interval=0.5, use_notify=False)

        worker_task = asyncio.create_task(run_worker())

        try:
            # Wait for exhaustion or timeout
            await asyncio.wait_for(exhausted.wait(), timeout=10.0)

            # Give worker time to process the exhaustion
            await asyncio.sleep(0.5)

            # Verify command moved to TSQ
            command_repo = PostgresCommandRepository(pool)
            metadata = await command_repo.get("payments", command_id)
            assert metadata is not None
            assert metadata.status == CommandStatus.IN_TROUBLESHOOTING_QUEUE
            assert len(attempts_seen) >= 2
        finally:
            await worker.stop(timeout=2.0)
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task

    @pytest.mark.asyncio
    async def test_exhaustion_does_not_send_reply(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
    ) -> None:
        """Test that exhausted commands do not send automatic replies."""
        command_id = uuid4()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            raise TransientCommandError("TIMEOUT", "Timeout")

        # Send command with reply_to
        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123"},
            reply_to="reports__replies",
        )

        # Worker with max_attempts=1
        worker = Worker(
            pool,
            domain="payments",
            registry=handler_registry,
            retry_policy=RetryPolicy(max_attempts=1, backoff_schedule=[1]),
        )

        received = await worker.receive()
        await worker.fail(received[0], TransientCommandError("TIMEOUT", "Timeout"))

        # Check no reply was sent (reply queue should be empty)
        pgmq = PgmqClient(pool)
        reply_messages = await pgmq.read("reports__replies", visibility_timeout=1, batch_size=10)
        assert len(reply_messages) == 0
