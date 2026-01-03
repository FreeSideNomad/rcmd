"""Integration tests for transient retry flow."""

import asyncio
import contextlib
from uuid import uuid4

import pytest
from psycopg_pool import AsyncConnectionPool

from commandbus import (
    Command,
    CommandBus,
    CommandStatus,
    HandlerContext,
    HandlerRegistry,
    PostgresAuditLogger,
    PostgresCommandRepository,
    RetryPolicy,
    TransientCommandError,
    Worker,
)
from commandbus.repositories.audit import AuditEventType


@pytest.mark.integration
class TestTransientRetryFlow:
    """Integration tests for transient error retry flow."""

    @pytest.mark.asyncio
    async def test_transient_error_updates_metadata(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that transient error updates last_error fields in metadata."""
        command_id = uuid4()

        # Register handler that raises TransientCommandError
        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            raise TransientCommandError("TIMEOUT", "Database connection timeout")

        # Send command
        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123", "amount": 100},
        )

        # Create worker with short backoff for testing
        worker = Worker(
            pool,
            domain="payments",
            registry=handler_registry,
            retry_policy=RetryPolicy(max_attempts=3, backoff_schedule=[1, 2, 5]),
        )

        # Receive and process the command
        received = await worker.receive()
        assert len(received) == 1

        # Process the command (should fail and update metadata)
        await worker.fail(
            received[0],
            TransientCommandError("TIMEOUT", "Database connection timeout"),
        )

        # Check metadata was updated with error info
        command_repo = PostgresCommandRepository(pool)
        metadata = await command_repo.get("payments", command_id)
        assert metadata is not None
        assert metadata.last_error_type == "TRANSIENT"
        assert metadata.last_error_code == "TIMEOUT"
        assert metadata.last_error_msg == "Database connection timeout"

    @pytest.mark.asyncio
    async def test_transient_error_records_failed_audit_event(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that transient error records FAILED audit event."""
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

        worker = Worker(
            pool,
            domain="payments",
            registry=handler_registry,
            retry_policy=RetryPolicy(max_attempts=3, backoff_schedule=[1, 2, 5]),
        )

        received = await worker.receive()
        await worker.fail(
            received[0],
            TransientCommandError("RATE_LIMIT", "Too many requests"),
        )

        # Check audit trail
        audit_logger = PostgresAuditLogger(pool)
        events = await audit_logger.get_events(command_id, domain="payments")

        # Should have SENT, RECEIVED, and FAILED events
        event_types = [e.event_type for e in events]
        assert AuditEventType.SENT.value in event_types
        assert AuditEventType.RECEIVED.value in event_types
        assert AuditEventType.FAILED.value in event_types

        # Check FAILED event details
        failed_event = next(e for e in events if e.event_type == AuditEventType.FAILED.value)
        assert failed_event.details["error_type"] == "TRANSIENT"
        assert failed_event.details["error_code"] == "RATE_LIMIT"

    @pytest.mark.asyncio
    async def test_message_reappears_after_visibility_timeout(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that message reappears after visibility timeout for retry."""
        command_id = uuid4()
        attempt_count = 0

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            nonlocal attempt_count
            attempt_count = context.attempt
            if context.attempt < 2:
                raise TransientCommandError("TIMEOUT", "Temporary failure")
            return {"status": "success"}

        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123"},
        )

        # Use very short visibility timeout for testing
        worker = Worker(
            pool,
            domain="payments",
            registry=handler_registry,
            visibility_timeout=1,
            retry_policy=RetryPolicy(max_attempts=3, backoff_schedule=[1, 2, 5]),
        )

        # First attempt - should fail
        received = await worker.receive()
        assert len(received) == 1
        assert received[0].context.attempt == 1

        # Simulate failure with 1 second backoff
        await worker.fail(
            received[0],
            TransientCommandError("TIMEOUT", "Temporary failure"),
        )

        # Wait for message to become visible again
        await asyncio.sleep(1.5)

        # Second attempt - should succeed
        received = await worker.receive()
        assert len(received) == 1
        assert received[0].context.attempt == 2

    @pytest.mark.asyncio
    async def test_unknown_exception_treated_as_transient(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that unknown exceptions are treated as transient errors."""
        command_id = uuid4()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            raise RuntimeError("Unexpected database error")

        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123"},
        )

        worker = Worker(
            pool,
            domain="payments",
            registry=handler_registry,
            retry_policy=RetryPolicy(max_attempts=3, backoff_schedule=[1, 2, 5]),
        )

        received = await worker.receive()
        await worker.fail(received[0], RuntimeError("Unexpected database error"))

        # Check metadata shows TRANSIENT error type
        command_repo = PostgresCommandRepository(pool)
        metadata = await command_repo.get("payments", command_id)
        assert metadata is not None
        assert metadata.last_error_type == "TRANSIENT"
        assert metadata.last_error_code == "RuntimeError"

    @pytest.mark.asyncio
    async def test_backoff_schedule_applied(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that backoff schedule is correctly applied to retries."""
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

        # Custom backoff schedule: 1s, 2s, 5s
        worker = Worker(
            pool,
            domain="payments",
            registry=handler_registry,
            visibility_timeout=30,
            retry_policy=RetryPolicy(max_attempts=4, backoff_schedule=[1, 2, 5]),
        )

        # First attempt
        received = await worker.receive()
        assert received[0].context.attempt == 1

        # Fail with backoff
        await worker.fail(
            received[0],
            TransientCommandError("TIMEOUT", "Timeout"),
        )

        # Message should not be visible immediately (backoff applied)
        immediate_receive = await worker.receive(visibility_timeout=1)
        assert len(immediate_receive) == 0

        # Wait for backoff to expire
        await asyncio.sleep(1.5)

        # Now should be visible for retry
        received = await worker.receive()
        assert len(received) == 1
        assert received[0].context.attempt == 2

    @pytest.mark.asyncio
    async def test_worker_run_handles_transient_errors(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that worker.run() properly handles transient errors."""
        command_id = uuid4()
        processed = asyncio.Event()
        attempts_seen: list[int] = []

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            attempts_seen.append(context.attempt)
            if context.attempt < 2:
                raise TransientCommandError("TIMEOUT", "First attempt fails")
            processed.set()
            return {"status": "success"}

        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123"},
        )

        worker = Worker(
            pool,
            domain="payments",
            registry=handler_registry,
            visibility_timeout=1,
            retry_policy=RetryPolicy(max_attempts=3, backoff_schedule=[1, 1, 1]),
        )

        # Run worker for a short time
        async def run_worker() -> None:
            await worker.run(concurrency=1, poll_interval=0.5, use_notify=False)

        worker_task = asyncio.create_task(run_worker())

        try:
            # Wait for successful processing or timeout
            await asyncio.wait_for(processed.wait(), timeout=5.0)

            # Give worker time to finish processing and update status
            await asyncio.sleep(0.5)

            # Should have seen at least 2 attempts (first failed, second succeeded)
            assert len(attempts_seen) >= 2
            assert 1 in attempts_seen
            assert 2 in attempts_seen

            # Verify command completed
            command_repo = PostgresCommandRepository(pool)
            metadata = await command_repo.get("payments", command_id)
            assert metadata is not None
            assert metadata.status == CommandStatus.COMPLETED
        finally:
            await worker.stop(timeout=2.0)
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task
