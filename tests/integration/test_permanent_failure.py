"""Integration tests for permanent failure flow."""

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
    PermanentCommandError,
    PostgresAuditLogger,
    PostgresCommandRepository,
    RetryPolicy,
    Worker,
)
from commandbus.repositories.audit import AuditEventType


@pytest.mark.integration
class TestPermanentFailureFlow:
    """Integration tests for permanent error handling flow."""

    @pytest.mark.asyncio
    async def test_permanent_error_updates_metadata(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that permanent error updates last_error fields in metadata."""
        command_id = uuid4()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("INVALID_ACCOUNT", "Account does not exist")

        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "invalid-123"},
        )

        worker = Worker(
            pool,
            domain="payments",
            registry=handler_registry,
            retry_policy=RetryPolicy(max_attempts=3, backoff_schedule=[1, 2, 5]),
        )

        received = await worker.receive()
        assert len(received) == 1

        await worker.fail_permanent(
            received[0],
            PermanentCommandError("INVALID_ACCOUNT", "Account does not exist"),
        )

        # Check metadata was updated with error info
        command_repo = PostgresCommandRepository(pool)
        metadata = await command_repo.get("payments", command_id)
        assert metadata is not None
        assert metadata.last_error_type == "PERMANENT"
        assert metadata.last_error_code == "INVALID_ACCOUNT"
        assert metadata.last_error_msg == "Account does not exist"

    @pytest.mark.asyncio
    async def test_permanent_error_sets_tsq_status(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that permanent error sets status to IN_TROUBLESHOOTING_QUEUE."""
        command_id = uuid4()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("BUSINESS_RULE", "Insufficient funds")

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
        )

        received = await worker.receive()
        await worker.fail_permanent(
            received[0],
            PermanentCommandError("BUSINESS_RULE", "Insufficient funds"),
        )

        # Check status
        command_repo = PostgresCommandRepository(pool)
        metadata = await command_repo.get("payments", command_id)
        assert metadata is not None
        assert metadata.status == CommandStatus.IN_TROUBLESHOOTING_QUEUE

    @pytest.mark.asyncio
    async def test_permanent_error_records_moved_to_tsq_audit_event(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that permanent error records MOVED_TO_TSQ audit event."""
        command_id = uuid4()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("VALIDATION", "Invalid amount format")

        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123", "amount": "invalid"},
        )

        worker = Worker(
            pool,
            domain="payments",
            registry=handler_registry,
        )

        received = await worker.receive()
        await worker.fail_permanent(
            received[0],
            PermanentCommandError("VALIDATION", "Invalid amount format"),
        )

        # Check audit trail
        audit_logger = PostgresAuditLogger(pool)
        events = await audit_logger.get_events(command_id, domain="payments")

        # Should have SENT, RECEIVED, and MOVED_TO_TSQ events
        event_types = [e.event_type for e in events]
        assert AuditEventType.SENT.value in event_types
        assert AuditEventType.RECEIVED.value in event_types
        assert AuditEventType.MOVED_TO_TSQ.value in event_types

        # Check MOVED_TO_TSQ event details
        tsq_event = next(e for e in events if e.event_type == AuditEventType.MOVED_TO_TSQ.value)
        assert tsq_event.details["error_code"] == "VALIDATION"
        assert tsq_event.details["error_msg"] == "Invalid amount format"

    @pytest.mark.asyncio
    async def test_permanent_error_archives_message(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that permanent error archives the message (not deletes)."""
        command_id = uuid4()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("PERMANENT", "Unrecoverable error")

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
        )

        received = await worker.receive()
        msg_id = received[0].msg_id
        await worker.fail_permanent(
            received[0],
            PermanentCommandError("PERMANENT", "Unrecoverable error"),
        )

        # Message should not be receivable anymore
        more_messages = await worker.receive()
        assert len(more_messages) == 0

        # But message should be archived (check archive table exists)
        async with pool.connection() as conn:
            result = await conn.execute(
                """
                SELECT msg_id FROM pgmq.a_payments__commands
                WHERE msg_id = %s
                """,
                (msg_id,),
            )
            archived = await result.fetchone()
            assert archived is not None
            assert archived[0] == msg_id

    @pytest.mark.asyncio
    async def test_permanent_error_no_retry(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that permanent errors do not allow retries."""
        command_id = uuid4()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("NO_RETRY", "Should not retry")

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
            retry_policy=RetryPolicy(max_attempts=5, backoff_schedule=[1, 1, 1, 1]),
        )

        # First attempt
        received = await worker.receive()
        assert len(received) == 1
        assert received[0].context.attempt == 1

        # Fail permanently
        await worker.fail_permanent(
            received[0],
            PermanentCommandError("NO_RETRY", "Should not retry"),
        )

        # Wait and try to receive - should get nothing (no retry)
        await asyncio.sleep(2)
        more_messages = await worker.receive()
        assert len(more_messages) == 0

        # Status should be IN_TROUBLESHOOTING_QUEUE
        command_repo = PostgresCommandRepository(pool)
        metadata = await command_repo.get("payments", command_id)
        assert metadata is not None
        assert metadata.status == CommandStatus.IN_TROUBLESHOOTING_QUEUE

    @pytest.mark.asyncio
    async def test_worker_run_handles_permanent_errors(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that worker.run() properly handles permanent errors."""
        command_id = uuid4()
        handler_called = asyncio.Event()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            handler_called.set()
            raise PermanentCommandError(
                "BUSINESS_RULE",
                "Cannot process this command",
                details={"reason": "test"},
            )

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

        async def run_worker() -> None:
            await worker.run(concurrency=1, poll_interval=0.5, use_notify=False)

        worker_task = asyncio.create_task(run_worker())

        try:
            # Wait for handler to be called
            await asyncio.wait_for(handler_called.wait(), timeout=5.0)

            # Give worker time to process the failure
            await asyncio.sleep(0.5)

            # Verify command moved to TSQ
            command_repo = PostgresCommandRepository(pool)
            metadata = await command_repo.get("payments", command_id)
            assert metadata is not None
            assert metadata.status == CommandStatus.IN_TROUBLESHOOTING_QUEUE
            assert metadata.last_error_type == "PERMANENT"
            assert metadata.last_error_code == "BUSINESS_RULE"
        finally:
            await worker.stop(timeout=2.0)
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task

    @pytest.mark.asyncio
    async def test_permanent_error_with_details(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that permanent error details are recorded in audit event."""
        command_id = uuid4()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError(
                "VALIDATION",
                "Multiple validation errors",
                details={
                    "errors": ["field1 is required", "field2 must be positive"],
                    "severity": "high",
                },
            )

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
        )

        received = await worker.receive()
        await worker.fail_permanent(
            received[0],
            PermanentCommandError(
                "VALIDATION",
                "Multiple validation errors",
                details={
                    "errors": ["field1 is required", "field2 must be positive"],
                    "severity": "high",
                },
            ),
        )

        # Check audit event has details
        audit_logger = PostgresAuditLogger(pool)
        events = await audit_logger.get_events(command_id, domain="payments")

        tsq_event = next(e for e in events if e.event_type == AuditEventType.MOVED_TO_TSQ.value)
        assert tsq_event.details["error_details"]["errors"] == [
            "field1 is required",
            "field2 must be positive",
        ]
        assert tsq_event.details["error_details"]["severity"] == "high"
