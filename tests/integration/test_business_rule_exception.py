"""Integration tests for BusinessRuleException flow."""

import asyncio
import contextlib
from uuid import uuid4

import pytest
from psycopg_pool import AsyncConnectionPool

from commandbus import (
    BusinessRuleException,
    Command,
    CommandBus,
    CommandStatus,
    HandlerContext,
    HandlerRegistry,
    PostgresAuditLogger,
    PostgresCommandRepository,
    RetryPolicy,
    Worker,
)
from commandbus.repositories.audit import AuditEventType


@pytest.mark.integration
class TestBusinessRuleExceptionFlow:
    """Integration tests for business rule exception handling flow."""

    @pytest.mark.asyncio
    async def test_business_rule_updates_metadata(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that business rule exception updates last_error fields in metadata."""
        command_id = uuid4()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            raise BusinessRuleException("ACCOUNT_CLOSED", "Account was closed")

        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "closed-123"},
        )

        worker = Worker(
            pool,
            domain="payments",
            registry=handler_registry,
            retry_policy=RetryPolicy(max_attempts=3, backoff_schedule=[1, 2, 5]),
        )

        received = await worker.receive()
        assert len(received) == 1

        await worker.fail_business_rule(
            received[0],
            BusinessRuleException("ACCOUNT_CLOSED", "Account was closed"),
        )

        # Check metadata was updated with error info
        command_repo = PostgresCommandRepository(pool)
        metadata = await command_repo.get("payments", command_id)
        assert metadata is not None
        assert metadata.last_error_type == "BUSINESS_RULE"
        assert metadata.last_error_code == "ACCOUNT_CLOSED"
        assert metadata.last_error_msg == "Account was closed"

    @pytest.mark.asyncio
    async def test_business_rule_sets_failed_status(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that business rule exception sets status to FAILED (not TSQ)."""
        command_id = uuid4()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            raise BusinessRuleException("INVALID_DATE", "Date is in the future")

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
        await worker.fail_business_rule(
            received[0],
            BusinessRuleException("INVALID_DATE", "Date is in the future"),
        )

        # Check status is FAILED, not IN_TROUBLESHOOTING_QUEUE
        command_repo = PostgresCommandRepository(pool)
        metadata = await command_repo.get("payments", command_id)
        assert metadata is not None
        assert metadata.status == CommandStatus.FAILED

    @pytest.mark.asyncio
    async def test_business_rule_records_audit_event(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that business rule exception records BUSINESS_RULE_FAILED audit event."""
        command_id = uuid4()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            raise BusinessRuleException("VALIDATION", "Business rule violated")

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
        await worker.fail_business_rule(
            received[0],
            BusinessRuleException("VALIDATION", "Business rule violated"),
        )

        # Check audit trail
        audit_logger = PostgresAuditLogger(pool)
        events = await audit_logger.get_events(command_id, domain="payments")

        # Should have SENT, RECEIVED, and BUSINESS_RULE_FAILED events
        event_types = [e.event_type for e in events]
        assert AuditEventType.SENT.value in event_types
        assert AuditEventType.RECEIVED.value in event_types
        assert AuditEventType.BUSINESS_RULE_FAILED.value in event_types

        # Check BUSINESS_RULE_FAILED event details
        br_event = next(
            e for e in events if e.event_type == AuditEventType.BUSINESS_RULE_FAILED.value
        )
        assert br_event.details["error_code"] == "VALIDATION"
        assert br_event.details["error_msg"] == "Business rule violated"

    @pytest.mark.asyncio
    async def test_business_rule_archives_message(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that business rule exception archives the message."""
        command_id = uuid4()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            raise BusinessRuleException("BUSINESS_RULE", "Cannot process")

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
        await worker.fail_business_rule(
            received[0],
            BusinessRuleException("BUSINESS_RULE", "Cannot process"),
        )

        # Message should not be receivable anymore
        more_messages = await worker.receive()
        assert len(more_messages) == 0

        # But message should be archived
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
    async def test_business_rule_no_retry(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that business rule exceptions do not allow retries."""
        command_id = uuid4()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            raise BusinessRuleException("NO_RETRY", "Should not retry")

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

        # Fail with business rule
        await worker.fail_business_rule(
            received[0],
            BusinessRuleException("NO_RETRY", "Should not retry"),
        )

        # Wait and try to receive - should get nothing (no retry)
        await asyncio.sleep(2)
        more_messages = await worker.receive()
        assert len(more_messages) == 0

        # Status should be FAILED
        command_repo = PostgresCommandRepository(pool)
        metadata = await command_repo.get("payments", command_id)
        assert metadata is not None
        assert metadata.status == CommandStatus.FAILED

    @pytest.mark.asyncio
    async def test_worker_run_handles_business_rule_exception(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that worker.run() properly handles business rule exceptions."""
        command_id = uuid4()
        handler_called = asyncio.Event()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            handler_called.set()
            raise BusinessRuleException(
                "ACCOUNT_CLOSED",
                "Account was closed before operation",
                details={"closed_date": "2024-01-01"},
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

            # Verify command is FAILED (not in TSQ)
            command_repo = PostgresCommandRepository(pool)
            metadata = await command_repo.get("payments", command_id)
            assert metadata is not None
            assert metadata.status == CommandStatus.FAILED
            assert metadata.last_error_type == "BUSINESS_RULE"
            assert metadata.last_error_code == "ACCOUNT_CLOSED"
        finally:
            await worker.stop(timeout=2.0)
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task

    @pytest.mark.asyncio
    async def test_business_rule_with_details(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that business rule exception details are recorded in audit event."""
        command_id = uuid4()

        @handler_registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            raise BusinessRuleException(
                "VALIDATION",
                "Multiple validation errors",
                details={
                    "errors": ["date is required", "amount must be positive"],
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
        await worker.fail_business_rule(
            received[0],
            BusinessRuleException(
                "VALIDATION",
                "Multiple validation errors",
                details={
                    "errors": ["date is required", "amount must be positive"],
                    "severity": "high",
                },
            ),
        )

        # Check audit event has details
        audit_logger = PostgresAuditLogger(pool)
        events = await audit_logger.get_events(command_id, domain="payments")

        br_event = next(
            e for e in events if e.event_type == AuditEventType.BUSINESS_RULE_FAILED.value
        )
        assert br_event.details["error_details"]["errors"] == [
            "date is required",
            "amount must be positive",
        ]
        assert br_event.details["error_details"]["severity"] == "high"
